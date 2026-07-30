from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from sqlite_agent_pkg.agent.protocol import sql_core_system_message
from sqlite_agent_pkg.compat.xml_v1 import parse_final, parse_tool_call, parse_tool_result
from sqlite_agent_pkg.agent.protocol import final_message, system_message, tool_call, tool_result
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
    pd.DataFrame(
        [
            {
                "id": row["id"],
                "pool_id": row.get("pool_id"),
                "db_id": row["db_id"],
                "language": row["language"],
                "sample_type": row["sample_type"],
                "messages": row["messages"],
            }
            for row in rows
        ]
    ).to_parquet(path, index=False)
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
            column_chunks.append(f"{name} {col_type}".strip())
            if col.get("pk"):
                primary_keys.append(str(name))
        parts.append(f"TABLE {table_name}({', '.join(column_chunks)})")
        if primary_keys:
            parts.append(f"PRIMARY KEY {table_name}({', '.join(primary_keys)})")
        for fk in table.get("foreign_keys", []):
            parts.append(f"FOREIGN KEY {table_name}.{fk.get('from')} -> {fk.get('table')}.{fk.get('to')}")
    return "\n".join(parts)


def build_sql_core_row(task: dict[str, Any]) -> dict[str, Any] | None:
    question = task.get("question_en")
    if not question:
        return None
    tables = task.get("gold_tables") or task.get("table_names") or []
    schema_result = get_schema(task["db_path"], list(tables))
    schema_text = schema_to_text(schema_result)
    return {
        "id": f"{task['pool_id']}.en.sql_core",
        "pool_id": task["pool_id"],
        "db_id": task["db_id"],
        "language": "en",
        "sample_type": "sql_core_en",
        "messages": [
            sql_core_system_message(),
            {"role": "user", "content": f"Database schema:\n{schema_text}\n\nQuestion:\n{question}"},
            {"role": "assistant", "content": str(task["gold_sql"]).strip().rstrip(";")},
        ],
        "gold_sql": task["gold_sql"],
        "gold_result": task.get("gold_result"),
        "answer_spec": task.get("answer_spec"),
    }


def build_trace_row(rollout_row: dict[str, Any], *, sample_type: str) -> dict[str, Any]:
    messages = normalize_agent_messages((rollout_row.get("rollout") or {}).get("messages", []))
    return {
        "id": f"{rollout_row['task_id']}.{sample_type}",
        "pool_id": rollout_row.get("pool_id"),
        "db_id": rollout_row["db_id"],
        "language": "en",
        "sample_type": sample_type,
        "messages": messages,
        "gold_sql": rollout_row.get("gold_sql"),
        "gold_result": rollout_row.get("gold_result"),
        "answer_spec": rollout_row.get("answer_spec"),
        "source_task_id": rollout_row.get("task_id"),
    }


def normalize_agent_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if role == "system":
            normalized.append(system_message())
        elif role == "assistant":
            final = parse_final(content)
            if final is not None:
                normalized.append(
                    {
                        "role": "assistant",
                        "content": final_message(str(final.get("final_sql") or ""), str(final.get("answer") or "")),
                    }
                )
                continue
            action = parse_tool_call(content)
            if action is not None:
                normalized.append({"role": "assistant", "content": tool_call(action)})
                continue
            normalized.append(message)
        elif role == "user":
            result = parse_tool_result(content)
            if result is not None:
                normalized.append({"role": "user", "content": tool_result(result)})
            else:
                normalized.append(message)
        else:
            normalized.append(message)
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an English-first formal SFT dataset from split tasks and real rollout buckets.")
    parser.add_argument("--tasks", required=True, help="Split task file such as dev/train jsonl.")
    parser.add_argument("--strict-pass")
    parser.add_argument("--equivalent-output")
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--output-parquet")
    parser.add_argument("--manifest")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sql-core-limit", type=int)
    parser.add_argument("--strict-pass-limit", type=int)
    parser.add_argument("--equivalent-limit", type=int)
    args = parser.parse_args()

    rng = random.Random(args.seed)

    task_rows = [row for row in iter_jsonl(Path(args.tasks)) if row.get("question_en")]
    rng.shuffle(task_rows)
    sql_core_rows = [row for row in (build_sql_core_row(task) for task in task_rows) if row is not None]
    if args.sql_core_limit is not None:
        sql_core_rows = sql_core_rows[: args.sql_core_limit]

    strict_pass_rows: list[dict[str, Any]] = []
    if args.strict_pass:
        raw = iter_jsonl(Path(args.strict_pass))
        rng.shuffle(raw)
        if args.strict_pass_limit is not None:
            raw = raw[: args.strict_pass_limit]
        strict_pass_rows = [build_trace_row(row, sample_type="agent_trace_en") for row in raw]

    equivalent_rows: list[dict[str, Any]] = []
    if args.equivalent_output:
        raw = iter_jsonl(Path(args.equivalent_output))
        rng.shuffle(raw)
        if args.equivalent_limit is not None:
            raw = raw[: args.equivalent_limit]
        equivalent_rows = [build_trace_row(row, sample_type="equivalent_trace_en") for row in raw]

    all_rows = sql_core_rows + strict_pass_rows + equivalent_rows
    rng.shuffle(all_rows)

    write_jsonl(Path(args.output_jsonl), all_rows)
    parquet_written = False
    if args.output_parquet:
        parquet_written = maybe_write_parquet(Path(args.output_parquet), all_rows)

    manifest = {
        "tasks": args.tasks,
        "strict_pass": args.strict_pass,
        "equivalent_output": args.equivalent_output,
        "rows": len(all_rows),
        "counts": {
            "sql_core_en": len(sql_core_rows),
            "agent_trace_en": len(strict_pass_rows),
            "equivalent_trace_en": len(equivalent_rows),
        },
        "output_jsonl": args.output_jsonl,
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
