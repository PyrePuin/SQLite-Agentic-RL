from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def lang_group(row: dict[str, Any]) -> str:
    if row.get("has_en") and row.get("has_zh"):
        return "paired_en_zh"
    if row.get("has_zh"):
        return "zh_only"
    if row.get("has_en"):
        return "en_only"
    return "unknown"


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    db_counts = Counter(row["db_id"] for row in rows)
    lang_counts = Counter(lang_group(row) for row in rows)
    flags = Counter()
    for row in rows:
        diff = row.get("difficulty") or {}
        for key in ["has_join", "has_group_by", "has_having", "has_order_by", "has_limit", "has_nested_query", "has_set_op"]:
            if diff.get(key):
                flags[key] += 1
    return {
        "rows": len(rows),
        "dbs": len(db_counts),
        "language_groups": dict(lang_counts),
        "difficulty_flags": dict(flags),
        "top_dbs": db_counts.most_common(20),
    }


def assign_db_splits(db_to_rows: dict[str, list[dict[str, Any]]], seed: int, train_frac: float, dev_frac: float) -> dict[str, str]:
    rng = random.Random(seed)
    db_items = list(db_to_rows.items())
    rng.shuffle(db_items)
    total_rows = sum(len(rows) for _, rows in db_items)
    target_train = total_rows * train_frac
    target_dev = total_rows * dev_frac
    totals = {"train": 0, "dev": 0, "final_eval": 0}
    assignment: dict[str, str] = {}

    for db_id, rows in sorted(db_items, key=lambda item: len(item[1]), reverse=True):
        deficits = {
            "train": target_train - totals["train"],
            "dev": target_dev - totals["dev"],
            "final_eval": (total_rows - target_train - target_dev) - totals["final_eval"],
        }
        candidates = [name for name, deficit in deficits.items() if deficit > 0]
        split = max(candidates or deficits, key=lambda name: deficits[name])
        assignment[db_id] = split
        totals[split] += len(rows)
    return assignment


def make_smoke(rows: list[dict[str, Any]], per_db: int, max_rows: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    by_db: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_db[row["db_id"]].append(row)
    smoke = []
    for db_id in sorted(by_db):
        candidates = list(by_db[db_id])
        rng.shuffle(candidates)
        smoke.extend(candidates[:per_db])
    rng.shuffle(smoke)
    return smoke[:max_rows]


def main() -> None:
    parser = argparse.ArgumentParser(description="Make DB-level splits from filtered task pool.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-frac", type=float, default=0.80)
    parser.add_argument("--dev-frac", type=float, default=0.10)
    parser.add_argument("--smoke-per-db", type=int, default=2)
    parser.add_argument("--smoke-max-rows", type=int, default=128)
    args = parser.parse_args()

    rows = read_jsonl(Path(args.input))
    by_db: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_db[row["db_id"]].append(row)

    assignment = assign_db_splits(by_db, args.seed, args.train_frac, args.dev_frac)
    splits: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "final_eval": []}
    for db_id, db_rows in by_db.items():
        splits[assignment[db_id]].extend(db_rows)

    out = Path(args.output_dir)
    for name, split_rows in splits.items():
        split_rows.sort(key=lambda row: row["pool_id"])
        write_jsonl(out / f"{name}.jsonl", split_rows)

    smoke = make_smoke(splits["dev"], args.smoke_per_db, args.smoke_max_rows, args.seed)
    smoke.sort(key=lambda row: row["pool_id"])
    write_jsonl(out / "dev_smoke.jsonl", smoke)

    db_sets = {name: set(row["db_id"] for row in split_rows) for name, split_rows in splits.items()}
    overlap_errors = {}
    names = list(db_sets)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            overlap = sorted(db_sets[left] & db_sets[right])
            if overlap:
                overlap_errors[f"{left}__{right}"] = overlap

    manifest = {
        "input": args.input,
        "seed": args.seed,
        "train_frac": args.train_frac,
        "dev_frac": args.dev_frac,
        "total": summarize(rows),
        "splits": {name: summarize(split_rows) for name, split_rows in splits.items()},
        "smoke": summarize(smoke),
        "db_overlap_errors": overlap_errors,
        "db_assignment": assignment,
        "outputs": {name: str(out / f"{name}.jsonl") for name in splits} | {"dev_smoke": str(out / "dev_smoke.jsonl")},
    }
    (out / "split_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ["seed", "total", "splits", "smoke", "db_overlap_errors", "outputs"]}, ensure_ascii=False, indent=2))
    if overlap_errors:
        raise SystemExit("DB split overlap detected")


if __name__ == "__main__":
    main()
