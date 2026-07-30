from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _metadata(sample: Any) -> dict[str, Any]:
    return _as_dict(getattr(sample, "metadata", None))


def _metrics(sample: Any) -> dict[str, Any]:
    meta = _metadata(sample)
    metrics = _as_dict(meta.get("sqlite_final_metrics"))
    return {
        "reward": float(metrics.get("reward", meta.get("sqlite_reward", 0.0)) or 0.0),
        "submitted": bool(metrics.get("submitted", False)),
        "strict_pass": bool(metrics.get("strict_pass", False)),
        "equivalent_output": bool(metrics.get("equivalent_output", False)),
        "pred_executable": bool(metrics.get("pred_executable", False)),
        "protocol_valid": bool(metrics.get("protocol_valid", False)),
        "canonical_protocol_valid": bool(metrics.get("canonical_protocol_valid", False)),
        "parse_failed": bool(metrics.get("parse_failed", False)),
        "budget_exceeded": bool(metrics.get("budget_exceeded", False)),
        "tool_steps": int(metrics.get("tool_steps", meta.get("sqlite_tool_calls", 0)) or 0),
    }


def _summary(samples: list[Any]) -> dict[str, float]:
    total = len(samples)
    if total == 0:
        return {}
    rows = [_metrics(sample) for sample in samples]
    return {
        "tasks": float(total),
        "avg_reward": sum(row["reward"] for row in rows) / total,
        "strict_pass_rate": sum(row["strict_pass"] for row in rows) / total,
        "equivalent_output_rate": sum(row["equivalent_output"] for row in rows) / total,
        "submitted_rate": sum(row["submitted"] for row in rows) / total,
        "pred_executable_rate": sum(row["pred_executable"] for row in rows) / total,
        "protocol_valid_rate": sum(row["protocol_valid"] for row in rows) / total,
        "canonical_protocol_valid_rate": sum(row["canonical_protocol_valid"] for row in rows) / total,
        "parse_failed_rate": sum(row["parse_failed"] for row in rows) / total,
        "budget_exceeded_rate": sum(row["budget_exceeded"] for row in rows) / total,
        "avg_tool_steps": sum(row["tool_steps"] for row in rows) / total,
    }


def _emit(record: dict[str, Any]) -> None:
    text = json.dumps(record, ensure_ascii=False, sort_keys=True)
    print(f"[sqlite-rl-metrics] {text}", flush=True)
    output = os.environ.get("SQLITE_RL_METRICS_JSONL")
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(text + "\n")


def log_rollout_data(rollout_id: int, args: Any, samples: list[Any], rollout_extra_metrics: dict[str, Any] | None, rollout_time: float) -> bool:
    metrics = _summary(samples)
    if rollout_extra_metrics is not None:
        for key, value in metrics.items():
            rollout_extra_metrics[f"rollout/{key}"] = value
    _emit({"kind": "rollout", "rollout_id": rollout_id, "metrics": metrics})
    return False

def log_eval_rollout_data(rollout_id: int, args: Any, data: dict[str, Any], extra_metrics: dict[str, Any] | None) -> bool:
    if extra_metrics is None:
        extra_metrics = {}
    for dataset_name, dataset in data.items():
        samples = dataset.get("samples")
        if samples is None:
            continue
        metrics = _summary(samples)
        for key, value in metrics.items():
            extra_metrics[f"eval/{dataset_name}/{key}"] = value
        _emit({"kind": "eval", "rollout_id": rollout_id, "dataset": dataset_name, "metrics": metrics})
    return False
