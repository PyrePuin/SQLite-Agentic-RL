from __future__ import annotations

import json
from typing import Any

from sqlite_agent_pkg.env.sqlite_tools import MINIMAL_TOOLS


def parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(text.strip())
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def extract_first_json_object(text: str) -> dict[str, Any] | None:
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


def is_single_json_object(text: str) -> bool:
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        return False
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return isinstance(obj, dict)


def normalize_action(action: dict[str, Any]) -> dict[str, Any] | None:
    action_type = action.get("type")
    if action_type not in (None, "tool_call"):
        return None
    name = (
        action.get("name")
        or action.get("function_name")
        or action.get("tool_name")
        or action.get("function")
        or action.get("tool")
    )
    if name not in MINIMAL_TOOLS:
        return None
    arguments = action.get("arguments")
    if arguments is None:
        arguments = action.get("parameters")
    if arguments is None:
        arguments = action.get("args", {})
    if not isinstance(arguments, dict):
        return None
    return {"name": str(name), "arguments": arguments}


def parse_json_v2_tool_call(text: str) -> tuple[dict[str, Any] | None, bool]:
    canonical = is_single_json_object(text)
    obj = json.loads(text.strip()) if canonical else extract_first_json_object(text)
    if obj is None:
        return None, False
    if obj.get("type") != "tool_call":
        return None, canonical
    action = normalize_action(obj)
    if action is None:
        return None, canonical
    if set(obj) != {"type", "name", "arguments"}:
        canonical = False
    return action, canonical


def parse_json_v2_final(text: str) -> tuple[dict[str, Any] | None, bool]:
    canonical = is_single_json_object(text)
    obj = json.loads(text.strip()) if canonical else extract_first_json_object(text)
    if obj is None:
        return None, False
    if obj.get("type") != "final":
        return None, canonical
    final_sql = obj.get("final_sql")
    if final_sql is None and "sql" in obj:
        final_sql = obj["sql"]
        canonical = False
    if not isinstance(final_sql, str):
        return None, canonical
    answer = obj.get("answer", "")
    if set(obj) != {"type", "final_sql", "answer"}:
        canonical = False
    return {"final_sql": final_sql, "answer": str(answer)}, canonical


def parse_tool_call(text: str) -> dict[str, Any] | None:
    action, canonical = parse_json_v2_tool_call(text)
    return action if canonical else None


def parse_final(text: str) -> dict[str, Any] | None:
    final, canonical = parse_json_v2_final(text)
    return final if canonical else None


def parse_tool_result(text: str) -> dict[str, Any] | None:
    result = parse_json_object(text)
    if result is not None:
        if result.get("type") == "tool_result" and isinstance(result.get("result"), dict):
            return result["result"]
        if "type" not in result:
            return result
        return None
    return None
