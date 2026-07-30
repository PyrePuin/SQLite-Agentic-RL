from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlite_agent_pkg.data.task_schema import load_tasks, task_to_row, write_jsonl


def difficulty_score(row: dict[str, Any]) -> int:
    difficulty = row.get("difficulty") or {}
    score = int(difficulty.get("num_tables", 1))
    for key in ("has_join", "has_group_by", "has_having", "has_nested_query", "has_set_op", "has_order_by"):
        score += int(bool(difficulty.get(key)))
    return score


def load_rows(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def normalize_task_rows(
    path: str | Path,
    *,
    english_only: bool,
    seed: int,
    limit: int,
    medium_ratio: float,
    hard_ratio: float,
    simple_ratio: float,
    max_empty_ratio: float,
) -> list[dict[str, Any]]:
    raw_rows = load_rows(path)
    rng = random.Random(seed)
    candidates = []
    for row in raw_rows:
        question = row.get("question_en") or row.get("question")
        if english_only and not row.get("question_en") and row.get("language") != "en":
            continue
        if not row.get("gold_result", {}).get("ok"):
            continue
        gold_rows = row.get("gold_result", {}).get("rows") or []
        row = dict(row)
        row["question"] = str(question)
        row["language"] = "en" if row.get("question_en") or row.get("language") == "en" else row.get("language", "unknown")
        row["task_id"] = str(row.get("task_id") or row.get("pool_id") or row.get("id"))
        row["_empty_gold"] = len(gold_rows) == 0
        candidates.append(row)

    hard = [row for row in candidates if difficulty_score(row) >= 5 and not row["_empty_gold"]]
    medium = [row for row in candidates if 3 <= difficulty_score(row) < 5 and not row["_empty_gold"]]
    simple = [row for row in candidates if difficulty_score(row) < 3 and not row["_empty_gold"]]
    empty = [row for row in candidates if row["_empty_gold"]]
    for bucket in (hard, medium, simple, empty):
        rng.shuffle(bucket)

    target_medium = int(limit * medium_ratio)
    target_hard = int(limit * hard_ratio)
    target_simple = int(limit * simple_ratio)
    selected = medium[:target_medium] + hard[:target_hard] + simple[:target_simple]
    remaining = limit - len(selected)
    if remaining > 0:
        selected += [row for row in [*medium[target_medium:], *hard[target_hard:], *simple[target_simple:]]][:remaining]
    max_empty = int(limit * max_empty_ratio)
    if len(selected) < limit and max_empty > 0:
        selected += empty[: min(max_empty, limit - len(selected))]
    if len(selected) < limit:
        seen = {row["task_id"] for row in selected}
        selected += [row for row in candidates if row["task_id"] not in seen][: limit - len(selected)]
    rng.shuffle(selected)
    for row in selected:
        row.pop("_empty_gold", None)
    return selected[:limit]


def manifest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    db_ids = sorted({row["db_id"] for row in rows})
    features = {
        "join": sum(bool((row.get("difficulty") or {}).get("has_join")) for row in rows),
        "group_by": sum(bool((row.get("difficulty") or {}).get("has_group_by")) for row in rows),
        "having": sum(bool((row.get("difficulty") or {}).get("has_having")) for row in rows),
        "nested": sum(bool((row.get("difficulty") or {}).get("has_nested_query")) for row in rows),
        "set_op": sum(bool((row.get("difficulty") or {}).get("has_set_op")) for row in rows),
        "multi_table": sum(int((row.get("difficulty") or {}).get("num_tables", 1)) >= 2 for row in rows),
        "empty_gold": sum(len((row.get("gold_result") or {}).get("rows") or []) == 0 for row in rows),
    }
    return {"tasks": len(rows), "db_count": len(db_ids), "db_ids": db_ids, "features": features}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build clean RL smoke task sets for SQLite Agentic RL V2.")
    parser.add_argument("--train-source", default="data/splits/v2_db_seed42/train.jsonl")
    parser.add_argument("--val-source", default="data/eval/sft_v2_json/hard_mini_dev_en.jsonl")
    parser.add_argument("--output-dir", default="data/rl/smoke_v1")
    parser.add_argument("--train-limit", type=int, default=96)
    parser.add_argument("--val-limit", type=int, default=60)
    parser.add_argument("--seed", type=int, default=600)
    parser.add_argument("--english-only", action="store_true", default=True)
    parser.add_argument("--medium-ratio", type=float, default=0.55)
    parser.add_argument("--hard-ratio", type=float, default=0.35)
    parser.add_argument("--simple-ratio", type=float, default=0.10)
    parser.add_argument("--max-empty-ratio", type=float, default=0.12)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    train_rows = normalize_task_rows(
        args.train_source,
        english_only=args.english_only,
        seed=args.seed,
        limit=args.train_limit,
        medium_ratio=args.medium_ratio,
        hard_ratio=args.hard_ratio,
        simple_ratio=args.simple_ratio,
        max_empty_ratio=args.max_empty_ratio,
    )
    val_rows = normalize_task_rows(
        args.val_source,
        english_only=True,
        seed=args.seed + 1,
        limit=args.val_limit,
        medium_ratio=0.40,
        hard_ratio=0.55,
        simple_ratio=0.05,
        max_empty_ratio=args.max_empty_ratio,
    )

    write_jsonl(output_dir / "train_tasks.jsonl", train_rows)
    write_jsonl(output_dir / "val_tasks.jsonl", val_rows)
    summary = {
        "seed": args.seed,
        "ratios": {
            "medium": args.medium_ratio,
            "hard": args.hard_ratio,
            "simple": args.simple_ratio,
            "max_empty": args.max_empty_ratio,
        },
        "train_source": args.train_source,
        "val_source": args.val_source,
        "train": manifest(train_rows),
        "val": manifest(val_rows),
        "outputs": {
            "train_tasks": str(output_dir / "train_tasks.jsonl"),
            "val_tasks": str(output_dir / "val_tasks.jsonl"),
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
