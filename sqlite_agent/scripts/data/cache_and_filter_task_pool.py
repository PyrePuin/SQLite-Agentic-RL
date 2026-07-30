from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT))

from sqlite_agent_pkg.env.sql_guard import is_readonly_select
from sqlite_agent_pkg.env.verifier import cache_gold_result


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sql_flags(sql: str) -> dict[str, bool]:
    low = f" {sql.lower()} "
    return {
        "has_join": " join " in low,
        "has_group_by": " group by " in low,
        "has_having": " having " in low,
        "has_order_by": " order by " in low,
        "has_limit": " limit " in low,
        "has_nested_query": low.count(" select ") > 1,
        "has_set_op": any(op in low for op in [" intersect ", " except ", " union "]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cache gold results and filter unified task pool.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--with-gold-output", required=True)
    parser.add_argument("--filtered-output", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--max-rows", type=int, default=500)
    parser.add_argument("--max-sql-length", type=int, default=1200)
    parser.add_argument("--timeout-sec", type=float, default=5.0)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    with_gold = []
    filtered = []
    reasons: Counter[str] = Counter()
    timings = []

    rows = list(read_jsonl(Path(args.input)))
    if args.limit is not None:
        rows = rows[: args.limit]

    for idx, row in enumerate(rows):
        row = dict(row)
        sql = row["gold_sql"]
        keep = True
        filter_reasons = []

        if not is_readonly_select(sql):
            keep = False
            filter_reasons.append("not_readonly_select")
        if len(sql) > args.max_sql_length:
            keep = False
            filter_reasons.append("sql_too_long")

        start = time.monotonic()
        try:
            gold_result = cache_gold_result(row["db_path"], sql, order_sensitive=row.get("answer_spec", {}).get("order_sensitive", False))
        except sqlite3.Error as exc:
            gold_result = {"ok": False, "error": repr(exc)}
        elapsed = time.monotonic() - start
        timings.append(elapsed)
        row["gold_result"] = gold_result
        row["gold_exec_time_sec"] = round(elapsed, 6)

        if elapsed > args.timeout_sec:
            keep = False
            filter_reasons.append("exec_too_slow")
        if not gold_result.get("ok"):
            keep = False
            filter_reasons.append("gold_exec_error")
        elif gold_result.get("row_count", 0) > args.max_rows:
            keep = False
            filter_reasons.append("too_many_rows")

        flags = sql_flags(sql)
        row["difficulty"] = {**row.get("difficulty", {}), **flags, "sql_length": len(sql)}
        row["filter"] = {"keep": keep, "reasons": filter_reasons}
        with_gold.append(row)
        if keep:
            filtered.append(row)
        for reason in filter_reasons or ["kept"]:
            reasons[reason] += 1

        if (idx + 1) % 1000 == 0:
            print(json.dumps({"processed": idx + 1, "kept": len(filtered), "reasons": dict(reasons)}, ensure_ascii=False))

    write_jsonl(Path(args.with_gold_output), with_gold)
    write_jsonl(Path(args.filtered_output), filtered)

    manifest = {
        "input": args.input,
        "rows": len(with_gold),
        "kept": len(filtered),
        "dropped": len(with_gold) - len(filtered),
        "reasons": dict(reasons),
        "max_rows": args.max_rows,
        "max_sql_length": args.max_sql_length,
        "timeout_sec": args.timeout_sec,
        "avg_exec_time_sec": sum(timings) / len(timings) if timings else None,
        "max_exec_time_sec": max(timings) if timings else None,
        "with_gold_output": args.with_gold_output,
        "filtered_output": args.filtered_output,
    }
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
