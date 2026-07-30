from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlite_agent_pkg.data.task_schema import load_tasks
from sqlite_agent_pkg.rl.slime_agent import render_prompt


def row_for_task(task: Any) -> dict[str, Any]:
    metadata = {
        "task_id": task.task_id,
        "db_path": str(task.db_path),
        "db_id": task.db_id,
        "question": task.question,
        "table_names": task.table_names,
        "gold_sql": task.gold_sql,
        "gold_result": task.gold_result,
    }
    reward_model = {
        "ground_truth": task.gold_sql,
        "gold_sql": task.gold_sql,
        **metadata,
    }
    return {
        "task_id": task.task_id,
        "prompt": render_prompt(task.question),
        "reward_model": json.dumps(reward_model, ensure_ascii=False),
        "metadata": json.dumps(metadata, ensure_ascii=False),
    }


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def maybe_write_parquet(rows: list[dict[str, Any]], path: Path) -> bool:
    try:
        import pandas as pd
    except Exception as exc:
        print(f"[slime-data] skip parquet: pandas import failed: {exc}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert V2 RL task JSONL into THUDM/slime prompt parquet.")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--output-parquet")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    tasks = load_tasks(args.tasks)
    if args.limit is not None:
        tasks = tasks[: args.limit]
    rows = [row_for_task(task) for task in tasks]
    write_jsonl(rows, Path(args.output_jsonl))
    print(f"[slime-data] wrote {len(rows)} rows to {args.output_jsonl}")
    if args.output_parquet and maybe_write_parquet(rows, Path(args.output_parquet)):
        print(f"[slime-data] wrote parquet to {args.output_parquet}")


if __name__ == "__main__":
    main()
