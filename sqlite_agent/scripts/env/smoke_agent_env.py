from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlite_agent_pkg.env.sqlite_tools import execute_sql, get_schema, list_tables, preview_rows
from sqlite_agent_pkg.env.verifier import verify_sql


def load_first_task(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                return json.loads(line)
    raise ValueError(f"empty task file: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test the SQLite agent environment on one real task.")
    parser.add_argument("--task-file", default="data/splits/v2_db_seed42/dev_smoke.jsonl")
    args = parser.parse_args()

    task = load_first_task(Path(args.task_file))
    db_path = task["db_path"]
    gold_tables = task.get("gold_tables") or task.get("table_names") or []
    first_table = gold_tables[0] if gold_tables else (task.get("table_names") or [""])[0]

    tables = list_tables(db_path)
    schema = get_schema(db_path, gold_tables[:2] or [first_table])
    preview = preview_rows(db_path, first_table, limit=2)
    executed = execute_sql(db_path, task["gold_sql"])
    verified = verify_sql(db_path, task["gold_sql"], task["gold_result"])

    summary = {
        "pool_id": task.get("pool_id"),
        "db_id": task["db_id"],
        "list_tables_ok": tables.get("ok"),
        "num_tables": len(tables.get("tables", [])),
        "get_schema_ok": schema.get("ok"),
        "preview_rows_ok": preview.get("ok"),
        "execute_sql_ok": executed.get("ok"),
        "verify_gold_correct": verified.get("correct"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    failed = [key for key, value in summary.items() if key.endswith("_ok") and not value]
    if failed or not summary["verify_gold_correct"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
