"""Legacy XML-envelope parsers used only by historical data tooling."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlite_agent_pkg.agent.parser import (
    extract_first_json_object,
    normalize_action,
    parse_json_object,
    parse_json_v2_final,
    parse_json_v2_tool_call,
)


def extract_tagged_json(text: str, tag: str) -> dict[str, Any] | None:
    pattern = re.compile(rf"<{tag}>\s*(.*?)\s*(?:</{tag}>|$)", flags=re.DOTALL)
    match = pattern.search(text)
    if not match:
        return None
    try:
        obj = json.loads(match.group(1))
    except json.JSONDecodeError:
        return extract_first_json_object(match.group(1))
    return obj if isinstance(obj, dict) else None


def parse_tool_call(text: str) -> dict[str, Any] | None:
    action, _ = parse_json_v2_tool_call(text)
    if action is not None:
        return action
    tagged = extract_tagged_json(text, "tool_call")
    return normalize_action(tagged) if tagged is not None else None


def parse_final(text: str) -> dict[str, Any] | None:
    final, _ = parse_json_v2_final(text)
    if final is not None:
        return final
    tagged = extract_tagged_json(text, "final")
    if tagged is None:
        return None
    if "final_sql" not in tagged and "sql" in tagged:
        tagged["final_sql"] = tagged["sql"]
    tagged.setdefault("answer", "")
    return tagged


def parse_tool_result(text: str) -> dict[str, Any] | None:
    result = parse_json_object(text)
    if result is not None:
        if result.get("type") == "tool_result" and isinstance(result.get("result"), dict):
            return result["result"]
        if "type" not in result:
            return result
        return None
    return extract_tagged_json(text, "tool_result")
