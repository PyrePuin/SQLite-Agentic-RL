from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "sqlite_agent"))

from sqlite_agent_pkg.agent.parser import parse_final, parse_json_v2_final, parse_json_v2_tool_call, parse_tool_call
from sqlite_agent_pkg.agent.protocol import system_message


def test_canonical_json_v2_tool_call_is_accepted() -> None:
    action, canonical = parse_json_v2_tool_call(
        '{"type":"tool_call","name":"list_tables","arguments":{}}'
    )
    assert action == {"name": "list_tables", "arguments": {}}
    assert canonical is True


def test_canonical_json_v2_final_is_accepted() -> None:
    final, canonical = parse_json_v2_final(
        '{"type":"final","final_sql":"SELECT 1","answer":"1"}'
    )
    assert final == {"final_sql": "SELECT 1", "answer": "1"}
    assert canonical is True


def test_formal_parser_rejects_xml_v1() -> None:
    assert parse_tool_call('<tool_call>{"name":"list_tables","arguments":{}}</tool_call>') is None
    assert parse_final('<final>{"final_sql":"SELECT 1"}</final>') is None
    assert (
        parse_tool_call(
            '<tool_call>{"type":"tool_call","name":"list_tables","arguments":{}}</tool_call>'
        )
        is None
    )
    assert (
        parse_final(
            '<final>{"type":"final","final_sql":"SELECT 1","answer":"1"}</final>'
        )
        is None
    )


def test_system_message_rejects_xml_v1() -> None:
    with pytest.raises(ValueError, match="json_v2"):
        system_message("xml_v1")
