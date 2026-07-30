from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "sqlite_agent"))

from sqlite_agent_pkg.data.path_utils import relativize_project_paths


def test_relativizes_local_v2_project_path() -> None:
    value = "/Users/example/LLMLearning/SQLite-Agentic-RL-V2/data/raw/spider/db.sqlite"
    assert relativize_project_paths(value) == "data/raw/spider/db.sqlite"


def test_relativizes_remote_v2_project_path() -> None:
    value = "/root/autodl-tmp/SQLite-Agentic-RL-V2/data/eval/tasks.jsonl"
    assert relativize_project_paths(value) == "data/eval/tasks.jsonl"


def test_recurses_through_json_values() -> None:
    value = {
        "db_path": "/Users/example/SQLite-Agentic-RL-V2/data/raw/db.sqlite",
        "sources": [{"db_path": "data/raw/already-relative.sqlite"}],
    }
    assert relativize_project_paths(value) == {
        "db_path": "data/raw/db.sqlite",
        "sources": [{"db_path": "data/raw/already-relative.sqlite"}],
    }


def test_preserves_unrelated_and_already_relative_strings() -> None:
    assert relativize_project_paths("data/sft/train.jsonl") == "data/sft/train.jsonl"
    assert relativize_project_paths("Qwen/Qwen2.5-Coder-3B-Instruct") == "Qwen/Qwen2.5-Coder-3B-Instruct"
