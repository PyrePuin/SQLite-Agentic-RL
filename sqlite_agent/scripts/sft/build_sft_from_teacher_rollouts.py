from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlite_agent_pkg.compat.xml_v1 import parse_final, parse_tool_call, parse_tool_result
from sqlite_agent_pkg.agent.protocol import system_message


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def normalize_assistant(content: str) -> tuple[str | None, str]:
    final = parse_final(content)
    if final is not None:
        return (
            canonical_json(
                {
                    "type": "final",
                    "final_sql": str(final.get("final_sql") or final.get("sql") or ""),
                    "answer": str(final.get("answer") or ""),
                }
            ),
            "final",
        )
    action = parse_tool_call(content)
    if action is not None:
        return (
            canonical_json(
                {
                    "type": "tool_call",
                    "name": str(action.get("name")),
                    "arguments": action.get("arguments") or {},
                }
            ),
            "tool_call",
        )
    return None, "invalid"


def normalize_user(content: str) -> str:
    result = parse_tool_result(content)
    if result is None:
        return content
    return canonical_json({"type": "tool_result", "result": result})


def convert_rollout(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    if not row.get("success"):
        return None, "not_success"
    rollout = row.get("rollout") or {}
    messages = rollout.get("messages")
    if not isinstance(messages, list) or len(messages) < 3:
        return None, "missing_messages"

    converted: list[dict[str, str]] = []
    assistant_types: Counter[str] = Counter()
    for message in messages:
        role = str(message.get("role"))
        content = str(message.get("content", ""))
        if role == "system":
            converted.append(system_message("json_v2"))
        elif role == "user":
            converted.append({"role": "user", "content": normalize_user(content)})
        elif role == "assistant":
            normalized, kind = normalize_assistant(content)
            if normalized is None:
                return None, "invalid_assistant"
            assistant_types[kind] += 1
            converted.append({"role": "assistant", "content": normalized})

    if assistant_types.get("final", 0) != 1:
        return None, "bad_final_count"
    if assistant_types.get("tool_call", 0) < 1:
        return None, "no_tool_call"

    return (
        {
            "id": f"{row.get('task_id')}__teacher_agent_real__json_v3",
            "db_id": row.get("db_id"),
            "variant": "teacher_agent_real_v3",
            "messages": converted,
            "source_id": row.get("task_id") or row.get("pool_id"),
            "protocol": "json_v2",
            "language": row.get("language"),
            "model": row.get("model"),
        },
        "ok",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert verified real teacher rollouts into V2/V3 JSON SFT messages.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")
    args = parser.parse_args()

    rows = read_jsonl(Path(args.input))
    converted: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    for row in rows:
        sample, reason = convert_rollout(row)
        reasons[reason] += 1
        if sample is not None:
            converted.append(sample)

    write_jsonl(Path(args.output), converted)
    manifest = {
        "input": args.input,
        "output": args.output,
        "input_rows": len(rows),
        "output_rows": len(converted),
        "reason_counts": dict(sorted(reasons.items())),
    }
    manifest_path = Path(args.manifest) if args.manifest else Path(args.output).with_suffix(".manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
