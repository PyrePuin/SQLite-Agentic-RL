from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .sqlite_tools import execute_sql


def result_hash(result: dict[str, Any]) -> str:
    payload = json.dumps(canonical_rows(result), ensure_ascii=False, sort_keys=True, default=repr)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_rows(result: dict[str, Any], *, order_sensitive: bool = False) -> list[list[str]]:
    rows = [[repr(value) for value in row] for row in result.get("rows", [])]
    return rows if order_sensitive else sorted(rows)


def normalize_cell(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 8)
    return value


def normalized_row(row: list[Any]) -> tuple[Any, ...]:
    return tuple(normalize_cell(value) for value in row)


def cache_gold_result(db_path: str | Path, sql: str, *, order_sensitive: bool = False) -> dict[str, Any]:
    result = execute_sql(db_path, sql, max_rows=None)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error"), "sql": result.get("sql")}
    result["row_count"] = len(result.get("rows", []))
    result["order_sensitive"] = order_sensitive
    result["duplicate_sensitive"] = True
    result["canonical_hash"] = result_hash(result)
    return result


def strict_match(pred: dict[str, Any], gold: dict[str, Any], *, order_sensitive: bool = False) -> bool:
    if pred.get("columns") != gold.get("columns"):
        return False
    return canonical_rows(pred, order_sensitive=order_sensitive) == canonical_rows(gold, order_sensitive=order_sensitive)


def value_match(pred: dict[str, Any], gold: dict[str, Any], *, order_sensitive: bool = False) -> bool:
    pred_columns = list(pred.get("columns") or [])
    gold_columns = list(gold.get("columns") or [])
    if len(pred_columns) != len(gold_columns):
        return False
    pred_rows = [normalized_row(row) for row in pred.get("rows", [])]
    gold_rows = [normalized_row(row) for row in gold.get("rows", [])]
    if order_sensitive:
        return pred_rows == gold_rows
    return Counter(pred_rows) == Counter(gold_rows)


def verify_sql(db_path: str | Path, pred_sql: str, gold_result: dict[str, Any]) -> dict[str, Any]:
    pred = execute_sql(db_path, pred_sql, max_rows=None)
    if not pred.get("ok"):
        return {"correct": False, "pred_executable": False, "pred_error": pred.get("error"), "pred_sql": pred.get("sql")}
    order_sensitive = bool(gold_result.get("order_sensitive", False))
    header_exact = strict_match(pred, gold_result, order_sensitive=order_sensitive)
    value_exact = value_match(pred, gold_result, order_sensitive=order_sensitive)
    return {
        "correct": value_exact,
        "pred_executable": True,
        "pred_result": pred,
        "gold_row_count": gold_result.get("row_count"),
        "pred_row_count": len(pred.get("rows", [])),
        "header_exact": header_exact,
        "value_exact": value_exact,
        "column_count_match": len(pred.get("columns") or []) == len(gold_result.get("columns") or []),
    }
