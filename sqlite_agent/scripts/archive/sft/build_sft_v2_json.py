from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any


V2_SYSTEM_PROMPT = """You are a SQLite data-analysis agent. Your job is to answer the user's question by using tools to inspect a SQLite database and then returning the final SQL and answer.

You may use these tools: list_tables, get_schema, preview_rows, execute_sql.

Return exactly one JSON object and no other text on every assistant turn.

For tool calls, use:
{"type":"tool_call","name":"list_tables","arguments":{}}
{"type":"tool_call","name":"get_schema","arguments":{"table_names":["table_a","table_b"]}}
{"type":"tool_call","name":"preview_rows","arguments":{"table_name":"table_a","limit":3}}
{"type":"tool_call","name":"execute_sql","arguments":{"sql":"SELECT ..."}}

For final answers, use:
{"type":"final","final_sql":"SELECT ...","answer":"..."}

Rules:
- Each assistant turn must contain exactly one JSON object.
- Do not output Markdown, explanations, XML tags, or text outside the JSON object.
- Tool-call JSON must use type, name, and arguments.
- Final JSON must use type, final_sql, and answer.
- SQL must be a single read-only SELECT or WITH query.
- If the SQL fails or is insufficient, continue investigating instead of finishing.
- Only output a final answer after a successful execute_sql result is enough to answer the question.
- final_sql must be the same SQL as the last successful execute_sql call."""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def first_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def tagged_json(text: str, tag: str) -> dict[str, Any] | None:
    match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(1))
    except json.JSONDecodeError:
        return first_json_object(match.group(1))
    return obj if isinstance(obj, dict) else None


def normalize_tool_action(obj: dict[str, Any]) -> dict[str, Any] | None:
    name = (
        obj.get("name")
        or obj.get("tool")
        or obj.get("function")
        or obj.get("tool_name")
        or obj.get("function_name")
    )
    arguments = obj.get("arguments")
    if arguments is None:
        arguments = obj.get("args")
    if arguments is None:
        arguments = obj.get("parameters")
    if arguments is None:
        arguments = {}
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return None
    return {"type": "tool_call", "name": name, "arguments": arguments}


def normalize_final(obj: dict[str, Any]) -> dict[str, Any] | None:
    final_sql = obj.get("final_sql")
    if final_sql is None:
        final_sql = obj.get("sql")
    if not isinstance(final_sql, str):
        return None
    return {"type": "final", "final_sql": final_sql, "answer": str(obj.get("answer", ""))}


def normalize_assistant(content: str) -> tuple[str | None, str]:
    tool_obj = tagged_json(content, "tool_call")
    if tool_obj is not None:
        action = normalize_tool_action(tool_obj)
        if action is not None:
            return json.dumps(action, ensure_ascii=False, separators=(",", ":")), "tool_call"

    final_obj = tagged_json(content, "final")
    if final_obj is not None:
        final = normalize_final(final_obj)
        if final is not None:
            return json.dumps(final, ensure_ascii=False, separators=(",", ":")), "final"

    raw_obj = first_json_object(content)
    if raw_obj is not None:
        if raw_obj.get("type") == "tool_call":
            action = normalize_tool_action(raw_obj)
            if action is not None:
                return json.dumps(action, ensure_ascii=False, separators=(",", ":")), "tool_call"
        if raw_obj.get("type") == "final":
            final = normalize_final(raw_obj)
            if final is not None:
                return json.dumps(final, ensure_ascii=False, separators=(",", ":")), "final"
        action = normalize_tool_action(raw_obj)
        if action is not None:
            return json.dumps(action, ensure_ascii=False, separators=(",", ":")), "tool_call"
        final = normalize_final(raw_obj)
        if final is not None:
            return json.dumps(final, ensure_ascii=False, separators=(",", ":")), "final"

    return None, "invalid"


def normalize_user(content: str) -> str:
    result_obj = tagged_json(content, "tool_result")
    if result_obj is not None:
        if "tool" in result_obj:
            result_obj["tool_name"] = result_obj.pop("tool")
        return json.dumps({"type": "tool_result", "result": result_obj}, ensure_ascii=False, separators=(",", ":"))
    return content


def convert_row(row: dict[str, Any], index: int) -> tuple[dict[str, Any] | None, list[str], Counter[str]]:
    errors: list[str] = []
    stats: Counter[str] = Counter()
    messages = row.get("messages")
    if not isinstance(messages, list):
        return None, [f"row {index}: missing messages"], stats

    converted: list[dict[str, str]] = []
    final_count = 0
    assistant_count = 0
    for msg_index, message in enumerate(messages):
        role = str(message.get("role", ""))
        content = str(message.get("content", ""))
        if role == "system":
            converted.append({"role": "system", "content": V2_SYSTEM_PROMPT})
            continue
        if role == "user":
            converted.append({"role": "user", "content": normalize_user(content)})
            continue
        if role == "assistant":
            assistant_count += 1
            normalized, kind = normalize_assistant(content)
            stats[f"assistant_{kind}"] += 1
            if normalized is None:
                errors.append(f"row {index} message {msg_index}: invalid assistant action")
                continue
            if kind == "final":
                final_count += 1
            converted.append({"role": "assistant", "content": normalized})
            continue
        errors.append(f"row {index} message {msg_index}: unsupported role {role}")

    if final_count != 1:
        errors.append(f"row {index}: expected exactly one final, got {final_count}")
    if assistant_count == 0:
        errors.append(f"row {index}: no assistant turns")
    if errors:
        return None, errors, stats

    out = dict(row)
    out["id"] = str(row.get("id") or f"row_{index:06d}") + "__json_v2"
    out["source_id"] = row.get("id")
    out["protocol"] = "json_v2"
    out["messages"] = converted
    return out, [], stats


def assistant_type(content: str) -> str:
    obj = first_json_object(content)
    if not obj:
        return "invalid"
    return str(obj.get("type", "missing_type"))


def audit_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    variant_counts: Counter[str] = Counter()
    assistant_types: Counter[str] = Counter()
    bad_examples: list[dict[str, Any]] = []
    message_lengths: list[int] = []
    for row_index, row in enumerate(rows):
        variant_counts[str(row.get("variant", "unknown"))] += 1
        for message in row.get("messages", []):
            content = str(message.get("content", ""))
            message_lengths.append(len(content))
            if message.get("role") == "assistant":
                kind = assistant_type(content)
                assistant_types[kind] += 1
                obj = first_json_object(content)
                if obj is None or kind not in {"tool_call", "final"} or "<tool_call>" in content or "<final>" in content:
                    if len(bad_examples) < 20:
                        bad_examples.append({"row": row_index, "content": content[:500]})
    message_lengths_sorted = sorted(message_lengths)
    p95 = message_lengths_sorted[int(len(message_lengths_sorted) * 0.95)] if message_lengths_sorted else 0
    p99 = message_lengths_sorted[int(len(message_lengths_sorted) * 0.99)] if message_lengths_sorted else 0
    return {
        "rows": len(rows),
        "variant_counts": dict(sorted(variant_counts.items())),
        "assistant_types": dict(sorted(assistant_types.items())),
        "bad_examples": bad_examples,
        "message_length_chars": {
            "max": max(message_lengths) if message_lengths else 0,
            "p95": p95,
            "p99": p99,
        },
        "valid": not bad_examples and set(assistant_types).issubset({"tool_call", "final"}),
    }


def row_length_stats(row: dict[str, Any]) -> tuple[int, int]:
    contents = [str(message.get("content", "")) for message in row.get("messages", [])]
    return (max((len(content) for content in contents), default=0), sum(len(content) for content in contents))


def filter_length_outliers(
    rows: list[dict[str, Any]],
    *,
    max_message_chars: int,
    max_total_chars: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for row in rows:
        max_message, total = row_length_stats(row)
        if max_message > max_message_chars or total > max_total_chars:
            dropped.append(
                {
                    "id": row.get("id"),
                    "db_id": row.get("db_id"),
                    "variant": row.get("variant"),
                    "max_message_chars": max_message,
                    "total_chars": total,
                }
            )
            continue
        kept.append(row)
    return kept, dropped


def make_anchor(row: dict[str, Any], messages: list[dict[str, str]], end_index: int, anchor_kind: str, seq: int) -> dict[str, Any]:
    return {
        "id": f"{row.get('source_id') or row.get('id')}__anchor_{anchor_kind}_{seq:04d}",
        "source_id": row.get("source_id") or row.get("id"),
        "db_id": row.get("db_id"),
        "variant": "protocol_anchor",
        "anchor_kind": anchor_kind,
        "protocol": "json_v2",
        "messages": messages[: end_index + 1],
    }


def build_anchors(rows: list[dict[str, Any]], target: int, seed: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        messages = row["messages"]
        assistant_indices = [idx for idx, msg in enumerate(messages) if msg.get("role") == "assistant"]
        if not assistant_indices:
            continue

        first_idx = assistant_indices[0]
        first_obj = first_json_object(messages[first_idx]["content"])
        if first_obj and first_obj.get("type") == "tool_call":
            candidates.append(make_anchor(row, messages, first_idx, "first_tool", len(candidates)))

        for idx in assistant_indices:
            obj = first_json_object(messages[idx]["content"])
            if obj and obj.get("type") == "tool_call" and obj.get("name") == "execute_sql":
                candidates.append(make_anchor(row, messages, idx, "execute_sql", len(candidates)))
                break

        last_idx = assistant_indices[-1]
        final_obj = first_json_object(messages[last_idx]["content"])
        if final_obj and final_obj.get("type") == "final":
            start = max(0, last_idx - 2)
            short_messages = [messages[0], messages[1]] + messages[start : last_idx + 1]
            candidates.append(
                {
                    "id": f"{row.get('source_id') or row.get('id')}__anchor_final_{len(candidates):04d}",
                    "source_id": row.get("source_id") or row.get("id"),
                    "db_id": row.get("db_id"),
                    "variant": "protocol_anchor",
                    "anchor_kind": "final",
                    "protocol": "json_v2",
                    "messages": short_messages,
                }
            )

    rng = random.Random(seed)
    rng.shuffle(candidates)
    return candidates[:target]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SFT v2 data by converting XML/tagged v1 data to pure JSON protocol.")
    parser.add_argument("--input", default="data/archive/sft_v1_xml_source_20260705/sft_v1_mixed_5000_repair5.jsonl")
    parser.add_argument("--output-dir", default="data/sft/v2_json")
    parser.add_argument("--anchor-target", type=int, default=600)
    parser.add_argument("--anchor-train-count", type=int, default=500)
    parser.add_argument("--max-message-chars", type=int, default=20000)
    parser.add_argument("--max-total-chars", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    rows = read_jsonl(input_path)
    converted: list[dict[str, Any]] = []
    errors: list[str] = []
    conversion_stats: Counter[str] = Counter()
    for index, row in enumerate(rows):
        converted_row, row_errors, stats = convert_row(row, index)
        conversion_stats.update(stats)
        if converted_row is not None:
            converted.append(converted_row)
        for error in row_errors:
            if len(errors) < 50:
                errors.append(error)

    converted_clean, dropped_length_outliers = filter_length_outliers(
        converted,
        max_message_chars=args.max_message_chars,
        max_total_chars=args.max_total_chars,
    )
    anchors = build_anchors(converted_clean, args.anchor_target, args.seed + 100)
    train_anchors = anchors[: args.anchor_train_count]
    official = list(converted_clean) + train_anchors
    random.Random(args.seed + 200).shuffle(official)

    converted_path = output_dir / "converted_5000.jsonl"
    converted_clean_path = output_dir / f"converted_clean_{len(converted_clean)}.jsonl"
    anchors_path = output_dir / "protocol_anchors_600.jsonl"
    official_path = output_dir / f"sft_v2_json_{len(official)}.jsonl"
    write_jsonl(converted_path, converted)
    write_jsonl(converted_clean_path, converted_clean)
    write_jsonl(anchors_path, anchors)
    write_jsonl(official_path, official)

    audit = {
        "converted": audit_rows(converted),
        "converted_clean": audit_rows(converted_clean),
        "anchors": audit_rows(anchors),
        "official": audit_rows(official),
        "conversion_stats": dict(sorted(conversion_stats.items())),
        "conversion_errors": errors,
        "length_filter": {
            "max_message_chars": args.max_message_chars,
            "max_total_chars": args.max_total_chars,
            "dropped_rows": len(dropped_length_outliers),
            "dropped_examples": dropped_length_outliers[:50],
        },
    }
    manifest = {
        "protocol": "json_v2",
        "source": str(input_path),
        "output_dir": str(output_dir),
        "converted_output": str(converted_path),
        "converted_clean_output": str(converted_clean_path),
        "anchors_output": str(anchors_path),
        "official_output": str(official_path),
        "source_rows": len(rows),
        "converted_rows": len(converted),
        "converted_clean_rows": len(converted_clean),
        "length_outlier_rows": len(dropped_length_outliers),
        "anchor_rows": len(anchors),
        "official_rows": len(official),
        "anchor_train_count": len(train_anchors),
        "seed": args.seed,
        "audit_valid": audit["official"]["valid"] and not errors,
        "notes": [
            "No teacher rollout is performed by this script.",
            "Assistant targets are normalized to one pure JSON object.",
            "Tool observations are normalized from XML tool_result tags to JSON user payloads.",
        ],
    }
    write_json(output_dir / "audit.json", audit)
    write_json(output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit("SFT v2 conversion finished with skipped/invalid rows; inspect audit.json")


if __name__ == "__main__":
    main()
