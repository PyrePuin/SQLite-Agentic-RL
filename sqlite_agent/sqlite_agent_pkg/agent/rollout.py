from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from sqlite_agent_pkg.agent.parser import parse_final, parse_tool_call
from sqlite_agent_pkg.env.sqlite_tools import execute_tool
from sqlite_agent_pkg.agent.protocol import tool_result


def rollout(
    *,
    db_path: str | Path,
    messages: list[dict[str, str]],
    generate: Callable[[list[dict[str, str]]], str],
    max_steps: int = 8,
) -> dict[str, Any]:
    transcript = list(messages)
    actions: list[dict[str, Any]] = []
    final: dict[str, Any] | None = None
    stop_reason = "max_steps"
    for _ in range(max_steps):
        content = generate(transcript)
        transcript.append({"role": "assistant", "content": content})
        final = parse_final(content)
        if final is not None:
            stop_reason = "final"
            break
        action = parse_tool_call(content)
        if action is None:
            transcript.append({"role": "user", "content": tool_result({"ok": False, "error": "parse_failed"})})
            stop_reason = "parse_failed"
            break
        observation = execute_tool(db_path, action)
        actions.append(action)
        transcript.append({"role": "user", "content": tool_result(json.loads(json.dumps(observation, ensure_ascii=False, default=repr)))})
    return {"messages": transcript, "actions": actions, "final": final, "stop_reason": stop_reason}
