from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def summarize_jsonl(path: Path) -> dict[str, Any]:
    rows = 0
    db_counts: Counter[str] = Counter()
    key_counts: Counter[str] = Counter()
    missing_db_path = 0
    missing_gold_sql = 0
    missing_question = 0

    for row in iter_jsonl(path):
        rows += 1
        if "db_id" in row:
            db_counts[str(row["db_id"])] += 1
        key_counts.update(row.keys())
        missing_db_path += int("db_path" not in row)
        missing_gold_sql += int("gold_sql" not in row and "query" not in row)
        missing_question += int("question" not in row)

    return {
        "path": str(path),
        "rows": rows,
        "dbs": len(db_counts),
        "top_dbs": db_counts.most_common(8),
        "keys": sorted(key_counts),
        "missing": {
            "db_path": missing_db_path,
            "gold_sql_or_query": missing_gold_sql,
            "question": missing_question,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect JSONL raw task files.")
    parser.add_argument("paths", nargs="+", help="JSONL files to inspect.")
    args = parser.parse_args()

    summaries = [summarize_jsonl(Path(path)) for path in args.paths]
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
