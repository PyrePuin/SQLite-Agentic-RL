from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

KEYWORDS = {
    "select", "from", "where", "join", "inner", "left", "right", "full", "outer", "on", "group",
    "by", "having", "order", "limit", "intersect", "except", "union", "as", "and", "or", "not",
    "in", "like", "between", "is", "null", "count", "sum", "avg", "min", "max", "distinct", "desc", "asc",
}
STOP_TABLE_TOKENS = KEYWORDS | {",", "(", ")"}


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


def normalize_gold_sql(sql: str) -> str:
    text = sql.strip().rstrip(";").lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([(),=<>+\-*/])\s*", r"\1", text)
    text = text.replace("!=", "<>")
    return text


def tokenize(sql: str) -> list[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[(),]", sql)


def extract_gold_tables(sql: str, known_tables: list[str]) -> list[str]:
    known = {table.lower(): table for table in known_tables}
    found: set[str] = set()
    tokens = tokenize(sql)
    for i, token in enumerate(tokens[:-1]):
        if token.lower() in {"from", "join"}:
            nxt = tokens[i + 1]
            key = nxt.lower()
            if key in known:
                found.add(known[key])
    return sorted(found)


def difficulty(sql: str, gold_tables: list[str]) -> dict[str, Any]:
    low = sql.lower()
    nested_selects = max(low.count("select") - 1, 0)
    return {
        "num_tables": len(gold_tables),
        "has_join": " join " in f" {low} ",
        "has_group_by": " group by " in low,
        "has_having": " having " in low,
        "has_order_by": " order by " in low,
        "has_limit": " limit " in low,
        "has_nested_query": nested_selects > 0,
        "has_set_op": any(op in low for op in [" intersect ", " except ", " union "]),
        "sql_length": len(sql),
    }


def add_source(record: dict[str, Any], row: dict[str, Any], source_file: str) -> None:
    source = row.get("dataset", "unknown")
    lang = row.get("language", "unknown")
    entry = {
        "task_id": row["task_id"],
        "source": source,
        "language": lang,
        "question": row["question"],
        "db_path": row["db_path"],
        "source_file": source_file,
    }
    record["sources"].append(entry)
    if lang == "en" and not record.get("question_en"):
        record["question_en"] = row["question"]
        record["spider_task_id"] = row["task_id"]
        record["spider_db_path"] = row["db_path"]
    if lang == "zh" and not record.get("question_zh"):
        record["question_zh"] = row["question"]
        record["cspider_task_id"] = row["task_id"]
        record["cspider_db_path"] = row["db_path"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a unified Spider/CSpider task pool.")
    parser.add_argument("--input", action="append", required=True, help="Raw task JSONL. Can be passed multiple times.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    input_counts: Counter[str] = Counter()

    for input_name in args.input:
        path = Path(input_name)
        for row in read_jsonl(path):
            input_counts[str(path)] += 1
            normalized_sql = normalize_gold_sql(row["gold_sql"])
            key = (row["db_id"], normalized_sql)
            if key not in grouped:
                gold_tables = extract_gold_tables(row["gold_sql"], row.get("table_names") or [])
                grouped[key] = {
                    "pool_id": f"pool_{len(grouped):06d}",
                    "db_id": row["db_id"],
                    "db_path": row["db_path"],
                    "gold_sql": row["gold_sql"].strip().rstrip(";"),
                    "normalized_gold_sql": normalized_sql,
                    "table_names": row.get("table_names") or [],
                    "gold_tables": gold_tables,
                    "difficulty": difficulty(row["gold_sql"], gold_tables),
                    "answer_spec": {
                        "mode": "strict",
                        "order_sensitive": False,
                        "duplicate_sensitive": True,
                    },
                    "question_en": None,
                    "question_zh": None,
                    "spider_task_id": None,
                    "cspider_task_id": None,
                    "sources": [],
                }
            add_source(grouped[key], row, str(path))

    rows = list(grouped.values())
    rows.sort(key=lambda row: (row["db_id"], row["normalized_gold_sql"]))
    for idx, row in enumerate(rows):
        row["pool_id"] = f"pool_{idx:06d}"
        langs = {source["language"] for source in row["sources"]}
        datasets = {source["source"] for source in row["sources"]}
        row["has_en"] = "en" in langs
        row["has_zh"] = "zh" in langs
        row["datasets"] = sorted(datasets)

    write_jsonl(Path(args.output), rows)

    pair_counts = Counter()
    db_counts = Counter()
    for row in rows:
        if row["has_en"] and row["has_zh"]:
            pair_counts["paired_en_zh"] += 1
        elif row["has_en"]:
            pair_counts["en_only"] += 1
        elif row["has_zh"]:
            pair_counts["zh_only"] += 1
        db_counts[row["db_id"]] += 1

    manifest = {
        "inputs": dict(input_counts),
        "pool_rows": len(rows),
        "dbs": len(db_counts),
        "pairing": dict(pair_counts),
        "top_dbs": db_counts.most_common(20),
        "output": args.output,
    }
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
