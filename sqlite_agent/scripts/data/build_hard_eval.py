from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
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


def difficulty_score(row: dict[str, Any]) -> float:
    d = row.get("difficulty") or {}
    score = 0.0
    score += 2.0 * max(0, int(d.get("num_tables") or 1) - 1)
    score += 2.0 if d.get("has_join") else 0.0
    score += 2.0 if d.get("has_group_by") else 0.0
    score += 1.0 if d.get("has_having") else 0.0
    score += 1.0 if d.get("has_order_by") else 0.0
    score += 0.5 if d.get("has_limit") else 0.0
    score += 3.0 if d.get("has_nested_query") else 0.0
    score += 3.0 if d.get("has_set_op") else 0.0
    score += min(float(d.get("sql_length") or 0) / 120.0, 2.0)
    return score


def choose_question(row: dict[str, Any], language_mode: str) -> tuple[str, str] | None:
    if language_mode == "en_only":
        q = row.get("question_en")
        return (str(q), "en") if q else None
    if language_mode == "zh_only":
        q = row.get("question_zh")
        return (str(q), "zh") if q else None
    q = row.get("question_en") or row.get("question_zh")
    if not q:
        return None
    return str(q), "en" if row.get("question_en") else "zh"


def has_feature(row: dict[str, Any], feature: str) -> bool:
    d = row.get("difficulty") or {}
    if feature == "multi_table":
        return int(d.get("num_tables") or 1) >= 2
    if feature == "aggregation":
        return bool(d.get("has_group_by") or d.get("has_having"))
    if feature == "nested_or_set":
        return bool(d.get("has_nested_query") or d.get("has_set_op"))
    if feature == "order_limit":
        return bool(d.get("has_order_by") or d.get("has_limit"))
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a harder DB-level eval slice from V2 task splits.")
    parser.add_argument("--input", default="data/splits/v2_db_seed42/dev.jsonl")
    parser.add_argument("--output", default="data/eval/mini_dev.jsonl")
    parser.add_argument("--manifest", help="Optional standalone manifest output; omitted for the consolidated data/eval manifest.")
    parser.add_argument("--target", type=int, default=120)
    parser.add_argument("--max-per-db", type=int, default=5)
    parser.add_argument("--language-mode", choices=["prefer_en", "en_only", "zh_only"], default="en_only")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    rows = []
    for row in read_jsonl(Path(args.input)):
        question = choose_question(row, args.language_mode)
        if question is None:
            continue
        text, language = question
        item = dict(row)
        item["question"] = text
        item["language"] = language
        item["task_id"] = item.get("pool_id") or item.get("task_id")
        item["_hard_score"] = difficulty_score(item)
        item["_hard_features"] = {
            "multi_table": has_feature(item, "multi_table"),
            "aggregation": has_feature(item, "aggregation"),
            "nested_or_set": has_feature(item, "nested_or_set"),
            "order_limit": has_feature(item, "order_limit"),
        }
        rows.append(item)

    rng.shuffle(rows)
    rows.sort(key=lambda row: (row["_hard_score"], str(row.get("db_id")), str(row.get("task_id"))), reverse=True)

    selected: list[dict[str, Any]] = []
    per_db: dict[str, int] = defaultdict(int)
    feature_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        db_id = str(row.get("db_id"))
        if per_db[db_id] >= args.max_per_db:
            continue
        selected.append(row)
        per_db[db_id] += 1
        for feature, present in row["_hard_features"].items():
            if present:
                feature_counts[feature] += 1
        if len(selected) >= args.target:
            break

    for row in selected:
        row.pop("_hard_score", None)
        row.pop("_hard_features", None)

    write_jsonl(Path(args.output), selected)
    manifest = {
        "input": args.input,
        "output": args.output,
        "target": args.target,
        "rows": len(selected),
        "db_count": len({row.get("db_id") for row in selected}),
        "max_per_db": args.max_per_db,
        "language_mode": args.language_mode,
        "feature_counts": dict(sorted(feature_counts.items())),
    }
    if args.manifest:
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
