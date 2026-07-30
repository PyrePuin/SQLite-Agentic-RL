from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlite_agent_pkg.agent.parser import parse_json_v2_final
from sqlite_agent_pkg.data.task_schema import resolve_db_path
from sqlite_agent_pkg.env.sql_guard import is_readonly_select
from sqlite_agent_pkg.env.verifier import cache_gold_result, verify_sql


def compute_sqlite_agent_reward(
    *,
    db_path: str | Path,
    gold_sql: str,
    final_sql: str | None,
    gold_result: dict[str, Any] | None = None,
    protocol_valid: bool = True,
    canonical_protocol_valid: bool = True,
    final_matches_last_execute: bool = True,
    parse_failed: bool = False,
    budget_exceeded: bool = False,
    unsafe_sql: bool = False,
    tool_steps: int = 0,
    max_tool_steps: int = 8,
) -> tuple[float, dict[str, Any]]:
    """Reward for V2 JSON-protocol SQLite agent rollouts.

    The reward is intentionally simple for the first RL smoke: correctness is the
    dominant term, while protocol/finalization failures are penalized enough to
    catch regressions from the SFT policy.
    """

    metrics: dict[str, Any] = {
        "submitted": final_sql is not None,
        "protocol_valid": protocol_valid,
        "canonical_protocol_valid": canonical_protocol_valid,
        "parse_failed": parse_failed,
        "budget_exceeded": budget_exceeded,
        "unsafe_sql": unsafe_sql,
        "final_matches_last_execute": final_matches_last_execute,
        "tool_steps": tool_steps,
    }

    penalty = 0.0
    if parse_failed:
        penalty -= 0.30
    if budget_exceeded:
        penalty -= 0.10
    if not protocol_valid:
        penalty -= 0.20
    elif not canonical_protocol_valid:
        penalty -= 0.05
    if not final_matches_last_execute:
        penalty -= 0.05
    if unsafe_sql:
        penalty -= 1.0
    if tool_steps > 6:
        penalty -= 0.02 * (tool_steps - 6)

    if final_sql is None:
        metrics.update(
            {
                "pred_executable": False,
                "strict_pass": False,
                "equivalent_output": False,
                "reward": penalty,
            }
        )
        return penalty, metrics

    resolved_db_path = resolve_db_path(str(db_path), Path.cwd())
    unsafe_sql = unsafe_sql or not is_readonly_select(final_sql)
    metrics["unsafe_sql"] = unsafe_sql
    if unsafe_sql:
        metrics.update(
            {
                "pred_executable": False,
                "strict_pass": False,
                "equivalent_output": False,
                "reward": -1.0,
            }
        )
        return -1.0, metrics

    gold = gold_result or cache_gold_result(resolved_db_path, gold_sql)
    verify = verify_sql(resolved_db_path, final_sql, gold) if gold.get("ok") else {"pred_executable": False}
    pred_executable = bool(verify.get("pred_executable"))
    strict_pass = bool(verify.get("header_exact") and verify.get("value_exact"))
    equivalent_output = bool(verify.get("value_exact"))

    if equivalent_output:
        outcome_reward = 1.0
        if not final_matches_last_execute:
            outcome_reward = min(outcome_reward, 0.80)
    elif pred_executable:
        outcome_reward = 0.20
    else:
        outcome_reward = 0.05
    reward = outcome_reward + penalty

    metrics.update(
        {
            "pred_executable": pred_executable,
            "strict_pass": strict_pass,
            "equivalent_output": equivalent_output,
            "verify": verify,
            "reward": reward,
        }
    )
    return reward, metrics


def reward_from_final_text(
    *,
    db_path: str | Path,
    gold_sql: str,
    text: str,
    gold_result: dict[str, Any] | None = None,
) -> tuple[float, dict[str, Any]]:
    final, canonical = parse_json_v2_final(text)
    return compute_sqlite_agent_reward(
        db_path=db_path,
        gold_sql=gold_sql,
        gold_result=gold_result,
        final_sql=final.get("final_sql") if final else None,
        protocol_valid=final is not None and canonical,
        canonical_protocol_valid=canonical,
        parse_failed=final is None,
        tool_steps=0,
    )
