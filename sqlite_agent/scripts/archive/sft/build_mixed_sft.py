from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from sqlite_agent_pkg.agent.protocol import final_message, sql_core_system_message, system_message, tool_call, tool_result
from sqlite_agent_pkg.env.sqlite_tools import execute_sql, get_schema


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def maybe_write_parquet(path: Path, rows: list[dict[str, Any]]) -> bool:
    try:
        import pandas as pd
    except ImportError:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    parquet_rows = []
    for row in rows:
        parquet_rows.append(
            {
                "id": row["id"],
                "pool_id": row["pool_id"],
                "db_id": row["db_id"],
                "language": row["language"],
                "sample_type": row["sample_type"],
                "messages": row["messages"],
            }
        )
    pd.DataFrame(parquet_rows).to_parquet(path, index=False)
    return True


def choose_language(row: dict[str, Any], rng: random.Random, english_rate: float) -> tuple[str, str] | None:
    question_zh = row.get("question_zh")
    question_en = row.get("question_en")
    if question_zh and question_en:
        return ("en", question_en) if rng.random() < english_rate else ("zh", question_zh)
    if question_zh:
        return "zh", question_zh
    if question_en:
        return "en", question_en
    return None


def schema_to_text(schema_result: dict[str, Any]) -> str:
    parts: list[str] = []
    for table_name, table in schema_result.get("tables", {}).items():
        columns = table.get("columns", [])
        column_chunks: list[str] = []
        primary_keys: list[str] = []
        for col in columns:
            name = col.get("name")
            col_type = col.get("type") or "UNKNOWN"
            chunk = f"{name} {col_type}".strip()
            if col.get("pk"):
                primary_keys.append(str(name))
            column_chunks.append(chunk)
        parts.append(f"TABLE {table_name}({', '.join(column_chunks)})")
        if primary_keys:
            parts.append(f"PRIMARY KEY {table_name}({', '.join(primary_keys)})")
        for fk in table.get("foreign_keys", []):
            from_col = fk.get("from")
            ref_table = fk.get("table")
            ref_col = fk.get("to")
            parts.append(f"FOREIGN KEY {table_name}.{from_col} -> {ref_table}.{ref_col}")
    return "\n".join(parts)


def answer_preview(row: dict[str, Any]) -> str:
    gold = row.get("gold_result") or {}
    if not gold.get("ok"):
        return ""
    return json.dumps(
        {
            "columns": gold.get("columns", []),
            "rows": gold.get("rows", [])[:3],
        },
        ensure_ascii=False,
    )


def infer_tables(row: dict[str, Any]) -> list[str]:
    tables = row.get("gold_tables") or row.get("table_names") or []
    if tables:
        return list(tables)
    lowered_sql = str(row["gold_sql"]).lower()
    return [table for table in row.get("table_names", []) if str(table).lower() in lowered_sql][:4]


def replace_first_identifier(sql: str, source: str, target: str) -> str:
    pattern = re.compile(rf"\b{re.escape(source)}\b", flags=re.IGNORECASE)
    return pattern.sub(target, sql, count=1)


def build_sql_core_row(row: dict[str, Any], *, language: str, question: str) -> dict[str, Any]:
    tables = infer_tables(row)
    schema_result = get_schema(row["db_path"], tables)
    schema_text = schema_to_text(schema_result)
    return {
        "id": f"{row['pool_id']}.{language}.sql_core",
        "pool_id": row["pool_id"],
        "db_id": row["db_id"],
        "language": language,
        "sample_type": "sql_core",
        "messages": [
            sql_core_system_message(),
            {"role": "user", "content": f"数据库结构:\n{schema_text}\n\n问题:\n{question}"},
            {"role": "assistant", "content": str(row["gold_sql"]).strip().rstrip(";")},
        ],
        "gold_sql": row["gold_sql"],
        "gold_result": row.get("gold_result"),
        "answer_spec": row.get("answer_spec"),
    }


def build_tool_trace_row(row: dict[str, Any], *, language: str, question: str) -> dict[str, Any]:
    tables = infer_tables(row)
    schema_result = get_schema(row["db_path"], tables)
    return {
        "id": f"{row['pool_id']}.{language}.tool_trace",
        "pool_id": row["pool_id"],
        "db_id": row["db_id"],
        "language": language,
        "sample_type": "tool_trace_bootstrap",
        "messages": [
            system_message(),
            {"role": "user", "content": question},
            {"role": "assistant", "content": tool_call({"name": "get_schema", "arguments": {"table_names": tables}})},
            {"role": "user", "content": tool_result(schema_result)},
            {"role": "assistant", "content": tool_call({"name": "execute_sql", "arguments": {"sql": row["gold_sql"]}})},
            {"role": "user", "content": tool_result(row.get("gold_result") or {})},
            {"role": "assistant", "content": final_message(str(row["gold_sql"]).strip().rstrip(";"), answer_preview(row))},
        ],
        "gold_sql": row["gold_sql"],
        "gold_result": row.get("gold_result"),
        "answer_spec": row.get("answer_spec"),
    }


def build_repair_row(row: dict[str, Any], *, language: str, question: str) -> dict[str, Any] | None:
    tables = infer_tables(row)
    if not tables:
        return None
    schema_result = get_schema(row["db_path"], tables)
    broken_table = f"{tables[0]}_missing"
    broken_sql = replace_first_identifier(str(row["gold_sql"]), tables[0], broken_table)
    if broken_sql == row["gold_sql"]:
        return None
    error_result = execute_sql(row["db_path"], broken_sql)
    if error_result.get("ok"):
        return None
    return {
        "id": f"{row['pool_id']}.{language}.repair",
        "pool_id": row["pool_id"],
        "db_id": row["db_id"],
        "language": language,
        "sample_type": "repair_missing_table",
        "messages": [
            system_message(),
            {"role": "user", "content": question},
            {"role": "assistant", "content": tool_call({"name": "get_schema", "arguments": {"table_names": tables}})},
            {"role": "user", "content": tool_result(schema_result)},
            {"role": "assistant", "content": tool_call({"name": "execute_sql", "arguments": {"sql": broken_sql}})},
            {"role": "user", "content": tool_result(error_result)},
            {"role": "assistant", "content": tool_call({"name": "execute_sql", "arguments": {"sql": row["gold_sql"]}})},
        ],
        "gold_sql": row["gold_sql"],
        "gold_result": row.get("gold_result"),
        "answer_spec": row.get("answer_spec"),
        "repair_meta": {
            "error_kind": "missing_table",
            "broken_sql": broken_sql,
            "target_sql": row["gold_sql"],
        },
    }


def sample_subset(rows: list[dict[str, Any]], *, rate: float, rng: random.Random) -> list[dict[str, Any]]:
    if rate <= 0:
        return []
    if rate >= 1:
        return list(rows)
    count = max(1, int(round(len(rows) * rate)))
    shuffled = list(rows)
    rng.shuffle(shuffled)
    return shuffled[:count]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a staged mixed SFT dataset for SQLite Agentic RL V2.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--output-parquet")
    parser.add_argument("--manifest")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--english-rate", type=float, default=0.2)
    parser.add_argument("--tool-trace-rate", type=float, default=0.45)
    parser.add_argument("--repair-rate", type=float, default=0.35)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    tasks = iter_jsonl(Path(args.input))
    if args.limit is not None:
        tasks = tasks[: args.limit]

    sampled_questions: list[tuple[dict[str, Any], str, str]] = []
    language_counts = {"zh": 0, "en": 0}
    for task in tasks:
        choice = choose_language(task, rng, args.english_rate)
        if choice is None:
            continue
        language, question = choice
        sampled_questions.append((task, language, question))
        language_counts[language] += 1

    rows: list[dict[str, Any]] = []
    type_counts = {"sql_core": 0, "tool_trace_bootstrap": 0, "repair_missing_table": 0}

    for task, language, question in sampled_questions:
        rows.append(build_sql_core_row(task, language=language, question=question))
        type_counts["sql_core"] += 1

    tool_trace_subset = sample_subset(sampled_questions, rate=args.tool_trace_rate, rng=rng)
    for task, language, question in tool_trace_subset:
        rows.append(build_tool_trace_row(task, language=language, question=question))
        type_counts["tool_trace_bootstrap"] += 1

    repair_subset = sample_subset(sampled_questions, rate=args.repair_rate, rng=rng)
    for task, language, question in repair_subset:
        repair_row = build_repair_row(task, language=language, question=question)
        if repair_row is None:
            continue
        rows.append(repair_row)
        type_counts["repair_missing_table"] += 1

    rng.shuffle(rows)

    output_jsonl = Path(args.output_jsonl)
    write_jsonl(output_jsonl, rows)
    parquet_written = False
    if args.output_parquet:
        parquet_written = maybe_write_parquet(Path(args.output_parquet), rows)

    manifest = {
        "input": args.input,
        "rows": len(rows),
        "base_tasks": len(sampled_questions),
        "seed": args.seed,
        "english_rate": args.english_rate,
        "tool_trace_rate": args.tool_trace_rate,
        "repair_rate": args.repair_rate,
        "language_counts": language_counts,
        "sample_type_counts": type_counts,
        "sample_type_ratios": {
            key: (value / len(rows) if rows else 0.0)
            for key, value in type_counts.items()
        },
        "output_jsonl": str(output_jsonl),
        "output_parquet": args.output_parquet if parquet_written else None,
        "parquet_written": parquet_written,
    }
    if args.manifest:
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
