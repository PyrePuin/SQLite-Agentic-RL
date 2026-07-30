from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "sqlite_agent"))

from sqlite_agent_pkg.env.verifier import cache_gold_result
from sqlite_agent_pkg.rl.reward import compute_sqlite_agent_reward


def make_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE numbers (value INTEGER)")
        connection.executemany("INSERT INTO numbers VALUES (?)", [(1,), (2,), (3,)])


def test_equivalent_result_receives_full_outcome_reward(tmp_path: Path) -> None:
    db_path = tmp_path / "fixture.sqlite"
    make_db(db_path)
    gold_sql = "SELECT SUM(value) AS total FROM numbers"
    gold = cache_gold_result(db_path, gold_sql)

    reward, metrics = compute_sqlite_agent_reward(
        db_path=db_path,
        gold_sql=gold_sql,
        gold_result=gold,
        final_sql="SELECT 1 + 2 + 3 AS result",
    )

    assert reward == 1.0
    assert metrics["equivalent_output"] is True
    assert metrics["strict_pass"] is False


def test_executable_wrong_query_receives_partial_reward(tmp_path: Path) -> None:
    db_path = tmp_path / "fixture.sqlite"
    make_db(db_path)

    reward, metrics = compute_sqlite_agent_reward(
        db_path=db_path,
        gold_sql="SELECT SUM(value) FROM numbers",
        final_sql="SELECT COUNT(*) FROM numbers",
    )

    assert reward == 0.2
    assert metrics["pred_executable"] is True
    assert metrics["equivalent_output"] is False


def test_unsafe_sql_is_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "fixture.sqlite"
    make_db(db_path)

    reward, metrics = compute_sqlite_agent_reward(
        db_path=db_path,
        gold_sql="SELECT SUM(value) FROM numbers",
        final_sql="DELETE FROM numbers",
    )

    assert reward == -1.0
    assert metrics["unsafe_sql"] is True
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM numbers").fetchone() == (3,)
