from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from sqlite_agent_pkg.agent.protocol import final_message, json_v2_tool_result, system_message, tool_call
from sqlite_agent_pkg.env.sqlite_tools import execute_tool


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def choose_question(row: dict[str, Any], prefer_en: bool = True) -> tuple[str, str] | None:
    if prefer_en and row.get("question_en"):
        return str(row["question_en"]), "en"
    if row.get("question_zh"):
        return str(row["question_zh"]), "zh"
    if row.get("question_en"):
        return str(row["question_en"]), "en"
    return None


def difficulty_label(row: dict[str, Any]) -> str:
    d = row.get("difficulty") or {}
    hard = bool(d.get("has_nested_query") or d.get("has_set_op") or (d.get("has_join") and (d.get("has_group_by") or d.get("has_having"))))
    medium = bool(d.get("has_join") or d.get("has_group_by") or d.get("has_having") or d.get("has_order_by") or d.get("has_limit"))
    if hard:
        return "hard"
    if medium:
        return "medium"
    return "simple"


def score(row: dict[str, Any]) -> float:
    d = row.get("difficulty") or {}
    value = 0.0
    value += 2.0 * max(0, int(d.get("num_tables") or 1) - 1)
    value += 2.0 if d.get("has_join") else 0.0
    value += 2.0 if d.get("has_group_by") else 0.0
    value += 1.0 if d.get("has_having") else 0.0
    value += 1.0 if d.get("has_order_by") else 0.0
    value += 0.5 if d.get("has_limit") else 0.0
    value += 3.0 if d.get("has_nested_query") else 0.0
    value += 3.0 if d.get("has_set_op") else 0.0
    value += min(float(d.get("sql_length") or 0) / 120.0, 2.0)
    return value


def has_literal(row: dict[str, Any]) -> bool:
    sql = str(row.get("gold_sql") or "")
    question = f"{row.get('question_en') or ''} {row.get('question_zh') or ''}"
    quoted_value = re.search(r"'[^']+'|\"[^\"]+\"", sql) is not None
    like_value = re.search(r"\blike\b", sql, flags=re.IGNORECASE) is not None
    quoted_question = any(mark in question for mark in ["'", '"', "“", "”", "‘", "’"])
    return quoted_value or like_value or quoted_question


def result_answer(observation: dict[str, Any]) -> str:
    payload = {"columns": observation.get("columns", []), "rows": observation.get("rows", [])}
    return json.dumps(payload, ensure_ascii=False)


def add_tool(messages: list[dict[str, str]], db_path: str, action: dict[str, Any]) -> dict[str, Any]:
    messages.append({"role": "assistant", "content": tool_call(action)})
    observation = execute_tool(db_path, action)
    messages.append({"role": "user", "content": json_v2_tool_result(observation)})
    return observation


def build_agent_sample(row: dict[str, Any], variant: str, *, preview: bool, list_first: bool = True) -> dict[str, Any] | None:
    question = choose_question(row)
    if question is None:
        return None
    text, language = question
    db_path = str(row["db_path"])
    gold_sql = str(row["gold_sql"])
    gold_tables = list(row.get("gold_tables") or row.get("table_names") or [])
    if not gold_tables:
        return None

    messages: list[dict[str, str]] = [system_message("json_v2"), {"role": "user", "content": text}]
    if list_first:
        add_tool(messages, db_path, {"name": "list_tables", "arguments": {}})
    add_tool(messages, db_path, {"name": "get_schema", "arguments": {"table_names": gold_tables}})
    if preview:
        add_tool(messages, db_path, {"name": "preview_rows", "arguments": {"table_name": gold_tables[0], "limit": 5}})
    observation = add_tool(messages, db_path, {"name": "execute_sql", "arguments": {"sql": gold_sql}})
    if not observation.get("ok"):
        return None
    messages.append({"role": "assistant", "content": final_message(gold_sql, result_answer(observation))})
    return {
        "id": f"{row.get('pool_id')}__{variant}__json_v3",
        "db_id": row.get("db_id"),
        "variant": variant,
        "messages": messages,
        "source_id": row.get("pool_id"),
        "protocol": "json_v2",
        "language": language,
        "difficulty_label": difficulty_label(row),
    }


def build_final_anchor(row: dict[str, Any]) -> dict[str, Any] | None:
    return build_agent_sample(row, "success_final_anchor", preview=False, list_first=False)


def build_projection_sample(row: dict[str, Any]) -> dict[str, Any] | None:
    question = choose_question(row)
    if question is None:
        return None
    text, language = question
    db_path = str(row["db_path"])
    gold_sql = str(row["gold_sql"])
    tables = list(row.get("gold_tables") or row.get("table_names") or [])
    if not tables:
        return None

    messages: list[dict[str, str]] = [
        system_message("json_v2"),
        {"role": "user", "content": text + "\nReturn only the columns requested by the question."},
    ]
    add_tool(messages, db_path, {"name": "get_schema", "arguments": {"table_names": tables}})
    observation = add_tool(messages, db_path, {"name": "execute_sql", "arguments": {"sql": gold_sql}})
    if not observation.get("ok"):
        return None
    messages.append({"role": "assistant", "content": final_message(gold_sql, result_answer(observation))})
    return {
        "id": f"{row.get('pool_id')}__projection_discipline__json_v3",
        "db_id": row.get("db_id"),
        "variant": "projection_discipline",
        "messages": messages,
        "source_id": row.get("pool_id"),
        "protocol": "json_v2",
        "language": language,
        "difficulty_label": difficulty_label(row),
    }


def take(candidates: list[dict[str, Any]], count: int, used: set[str]) -> list[dict[str, Any]]:
    selected = []
    for row in candidates:
        pool_id = str(row.get("pool_id"))
        if pool_id in used:
            continue
        selected.append(row)
        used.add(pool_id)
        if len(selected) >= count:
            break
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Build V3 augmented JSON SFT data from V2 plus targeted hard behavior samples.")
    parser.add_argument("--base", default="data/sft/v2_json/sft_v2_json_5486.jsonl")
    parser.add_argument("--train", default="data/splits/v2_db_seed42/train.jsonl")
    parser.add_argument("--output-dir", default="outputs/sft/v3_json_ablation")
    parser.add_argument("--hard-agent", type=int, default=380)
    parser.add_argument("--literal", type=int, default=220)
    parser.add_argument("--final-anchor", type=int, default=180)
    parser.add_argument("--projection", type=int, default=140)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    base = read_jsonl(Path(args.base))
    train = read_jsonl(Path(args.train))
    rng.shuffle(train)
    train.sort(key=lambda row: (score(row), str(row.get("pool_id"))), reverse=True)

    used: set[str] = set()
    augmentations: list[dict[str, Any]] = []

    hard_candidates = [row for row in train if difficulty_label(row) == "hard" and choose_question(row)]
    literal_candidates = [row for row in train if has_literal(row) and choose_question(row)]
    final_candidates = [row for row in train if difficulty_label(row) in {"medium", "hard"} and choose_question(row)]
    projection_candidates = [
        row
        for row in train
        if (row.get("difficulty") or {}).get("has_group_by")
        or (row.get("difficulty") or {}).get("has_order_by")
        or (row.get("difficulty") or {}).get("has_join")
    ]

    for row in take(hard_candidates, args.hard_agent, used):
        sample = build_agent_sample(row, "hard_agent_trace_v3", preview=has_literal(row))
        if sample:
            augmentations.append(sample)
    for row in take(literal_candidates, args.literal, used):
        sample = build_agent_sample(row, "literal_grounding_trace", preview=True)
        if sample:
            augmentations.append(sample)
    for row in take(final_candidates, args.final_anchor, used):
        sample = build_final_anchor(row)
        if sample:
            augmentations.append(sample)
    for row in take(projection_candidates, args.projection, used):
        sample = build_projection_sample(row)
        if sample:
            augmentations.append(sample)

    all_rows = base + augmentations
    output_dir = Path(args.output_dir)
    output_path = output_dir / f"sft_v3_json_{len(all_rows)}.jsonl"
    write_jsonl(output_path, all_rows)

    manifest = {
        "base": args.base,
        "train": args.train,
        "output": str(output_path),
        "base_rows": len(base),
        "augmentation_rows": len(augmentations),
        "total_rows": len(all_rows),
        "augmentation_variant_counts": dict(sorted(Counter(row.get("variant") for row in augmentations).items())),
        "all_variant_counts": dict(sorted(Counter(row.get("variant") for row in all_rows).items())),
        "augmentation_difficulty_counts": dict(sorted(Counter(row.get("difficulty_label", "unknown") for row in augmentations).items())),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
