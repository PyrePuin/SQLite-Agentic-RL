from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlite_agent_pkg.agent.protocol import sql_core_system_message
from sqlite_agent_pkg.env.sqlite_tools import get_schema


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


def build_row(row: dict[str, Any], *, language: str, question: str) -> dict[str, Any]:
    tables = row.get("gold_tables") or row.get("table_names") or []
    schema_result = get_schema(row["db_path"], tables)
    schema_text = schema_to_text(schema_result)
    user_content = f"数据库结构:\n{schema_text}\n\n问题:\n{question}"
    return {
        "id": f"{row['pool_id']}.{language}.sql_core",
        "pool_id": row["pool_id"],
        "db_id": row["db_id"],
        "language": language,
        "sample_type": "sql_core",
        "messages": [
            sql_core_system_message(),
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": row["gold_sql"].strip().rstrip(";")},
        ],
        "gold_sql": row["gold_sql"],
        "gold_result": row.get("gold_result"),
        "answer_spec": row.get("answer_spec"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build direct SQL core SFT samples from V2 split tasks.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--output-parquet")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--english-rate", type=float, default=0.2)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    tasks = iter_jsonl(Path(args.input))
    rng.shuffle(tasks)
    if args.limit is not None:
        tasks = tasks[: args.limit]

    rows: list[dict[str, Any]] = []
    language_counts = {"zh": 0, "en": 0}
    for task in tasks:
        choice = choose_language(task, rng, args.english_rate)
        if choice is None:
            continue
        language, question = choice
        rows.append(build_row(task, language=language, question=question))
        language_counts[language] += 1

    output_jsonl = Path(args.output_jsonl)
    write_jsonl(output_jsonl, rows)
    parquet_written = False
    if args.output_parquet:
        parquet_written = maybe_write_parquet(Path(args.output_parquet), rows)

    print(
        json.dumps(
            {
                "rows": len(rows),
                "language_counts": language_counts,
                "output_jsonl": str(output_jsonl),
                "output_parquet": args.output_parquet if parquet_written else None,
                "parquet_written": parquet_written,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
