from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "sqlite_agent"))

from sqlite_agent_pkg.env.sqlite_tools import execute_sql


def test_execute_sql_preserves_values_for_duplicate_column_names(tmp_path: Path) -> None:
    db_path = tmp_path / "fixture.sqlite"
    with sqlite3.connect(db_path):
        pass

    result = execute_sql(db_path, "SELECT 1 AS x, 2 AS x")

    assert result["ok"] is True
    assert result["columns"] == ["x", "x"]
    assert result["rows"] == [[1, 2]]
