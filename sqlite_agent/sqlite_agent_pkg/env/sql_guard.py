from __future__ import annotations

import re


FORBIDDEN = re.compile(
    r"\b(attach|alter|create|delete|detach|drop|insert|pragma|replace|update|vacuum)\b",
    flags=re.IGNORECASE,
)
READONLY_START = re.compile(r"^\s*(select|with)\b", flags=re.IGNORECASE)


def normalize_sql(sql: str) -> str:
    return sql.strip().rstrip(";")


def has_single_statement(sql: str) -> bool:
    text = sql.strip()
    if not text:
        return False
    if text.endswith(";"):
        text = text[:-1]
    return ";" not in text


def is_readonly_select(sql: str) -> bool:
    text = normalize_sql(sql)
    if not text:
        return False
    if not has_single_statement(sql):
        return False
    if FORBIDDEN.search(text):
        return False
    return bool(READONLY_START.match(text))


def guard_sql(sql: str) -> dict[str, object]:
    normalized = normalize_sql(sql)
    if not normalized:
        return {"ok": False, "sql": normalized, "error": "empty_sql"}
    if not has_single_statement(sql):
        return {"ok": False, "sql": normalized, "error": "multiple_statements"}
    if FORBIDDEN.search(normalized):
        return {"ok": False, "sql": normalized, "error": "forbidden_keyword"}
    if not READONLY_START.match(normalized):
        return {"ok": False, "sql": normalized, "error": "not_select_or_with"}
    return {"ok": True, "sql": normalized}
