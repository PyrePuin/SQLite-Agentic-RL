from __future__ import annotations

import json
from typing import Any

from sqlite_agent_pkg.env.sqlite_tools import MINIMAL_TOOLS


JSON_V2_SYSTEM_PROMPT = """You are a SQLite data-analysis agent. Your job is to answer the user's question by using tools to inspect a SQLite database and then returning the final SQL and answer.

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
- final_sql must be the same SQL as the last successful execute_sql call.
- Keep answer short. Do not enumerate long result lists; summarize them in one brief sentence."""

SYSTEM_PROMPT = JSON_V2_SYSTEM_PROMPT
SQL_CORE_SYSTEM_PROMPT = "You are in direct SQL mode. A SQLite schema is provided. Output only one executable read-only SQLite SELECT/WITH query."


def action(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "tool_call", "name": name, "arguments": arguments or {}}


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def tool_call(action_payload: dict[str, Any]) -> str:
    return _dumps(action(str(action_payload.get("name")), action_payload.get("arguments") or {}))


def tool_result(result: dict[str, Any]) -> str:
    return json_v2_tool_result(result)


def json_v2_tool_result(result: dict[str, Any]) -> str:
    cleaned = dict(result)
    if "tool" in cleaned:
        cleaned["tool_name"] = cleaned.pop("tool")
    return _dumps({"type": "tool_result", "result": cleaned})


def final_message(sql: str, answer: str = "") -> str:
    return _dumps({"type": "final", "final_sql": sql, "answer": answer})


def system_message(protocol: str = "json_v2") -> dict[str, str]:
    if protocol != "json_v2":
        raise ValueError(
            f"formal runtime only supports json_v2, received protocol={protocol!r}"
        )
    return {"role": "system", "content": JSON_V2_SYSTEM_PROMPT + "\nAvailable tools: " + ", ".join(MINIMAL_TOOLS)}


def sql_core_system_message() -> dict[str, str]:
    return {"role": "system", "content": SQL_CORE_SYSTEM_PROMPT}
