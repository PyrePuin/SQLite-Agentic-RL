from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .sql_guard import guard_sql


MINIMAL_TOOLS = ["list_tables", "get_schema", "preview_rows", "execute_sql"]
DEFAULT_PREVIEW_LIMIT = 5
MAX_PREVIEW_LIMIT = 20
MAX_OBSERVATION_ROWS = 100


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _connect_checked(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    return connect_readonly(path)


def list_tables(db_path: str | Path) -> dict[str, Any]:
    try:
        conn = _connect_checked(db_path)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        conn.close()
        return {"ok": True, "tables": [row["name"] for row in rows]}
    except (OSError, sqlite3.Error) as exc:
        return {"ok": False, "error": str(exc)}


def get_schema(db_path: str | Path, table_names: list[str]) -> dict[str, Any]:
    try:
        conn = _connect_checked(db_path)
        known_tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        out: dict[str, Any] = {}
        missing: list[str] = []
        for table in table_names:
            if table not in known_tables:
                missing.append(table)
                continue
            columns = [dict(row) for row in conn.execute(f"PRAGMA table_info({quote_identifier(table)})")]
            foreign_keys = [dict(row) for row in conn.execute(f"PRAGMA foreign_key_list({quote_identifier(table)})")]
            out[table] = {"columns": columns, "foreign_keys": foreign_keys}
        conn.close()
        return {"ok": len(missing) == 0, "tables": out, "missing_tables": missing}
    except (OSError, sqlite3.Error) as exc:
        return {"ok": False, "error": str(exc)}


def preview_rows(db_path: str | Path, table_name: str, limit: int = 5) -> dict[str, Any]:
    limit = max(1, min(int(limit), MAX_PREVIEW_LIMIT))
    sql = f"SELECT * FROM {quote_identifier(table_name)} LIMIT {limit}"
    result = execute_sql(db_path, sql, max_rows=limit)
    if not result.get("ok"):
        return {"ok": False, "table": table_name, "error": result.get("error")}
    return {
        "ok": True,
        "table": table_name,
        "columns": result["columns"],
        "rows": result["rows"],
        "row_count": result["row_count"],
        "truncated": result["truncated"],
    }


def execute_sql(db_path: str | Path, sql: str, max_rows: int | None = MAX_OBSERVATION_ROWS) -> dict[str, Any]:
    guard = guard_sql(sql)
    if not guard["ok"]:
        return {"ok": False, "error": guard["error"], "sql": guard["sql"]}
    try:
        conn = _connect_checked(db_path)
        cursor = conn.execute(str(guard["sql"]))
        fetch_limit = None if max_rows is None else max(1, int(max_rows))
        rows = cursor.fetchall() if fetch_limit is None else cursor.fetchmany(fetch_limit + 1)
        columns = [item[0] for item in cursor.description or []]
        truncated = False
        if fetch_limit is not None and len(rows) > fetch_limit:
            truncated = True
            rows = rows[:fetch_limit]
        result = {
            "ok": True,
            "sql": str(guard["sql"]),
            "columns": columns,
            "rows": [[row[index] for index in range(len(columns))] for row in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }
        conn.close()
        return result
    except (OSError, sqlite3.Error) as exc:
        return {"ok": False, "error": str(exc), "sql": str(guard["sql"])}


def execute_tool(db_path: str | Path, action: dict[str, Any]) -> dict[str, Any]:
    name = action.get("name")
    args = action.get("arguments", {})
    if not isinstance(args, dict):
        return {"ok": False, "error": "invalid_arguments"}
    if name == "list_tables":
        return list_tables(db_path)
    if name == "get_schema":
        raw = args.get("table_names") or args.get("table_name") or args.get("tables") or args.get("table")
        table_names = [str(item) for item in raw] if isinstance(raw, list) else [str(raw)]
        return get_schema(db_path, table_names)
    if name == "preview_rows":
        table_name = args.get("table_name") or args.get("table") or ""
        return preview_rows(db_path, str(table_name), int(args.get("limit", DEFAULT_PREVIEW_LIMIT)))
    if name == "execute_sql":
        return execute_sql(db_path, str(args.get("sql", "")))
    return {"ok": False, "error": "unknown_tool", "tool": name}
