from __future__ import annotations

from typing import Any


PROJECT_MARKERS = ("SQLite-Agentic-RL", "SQLite-Agentic-RL-V2")


def _relativize_string(value: str) -> str:
    for marker in PROJECT_MARKERS:
        marker_with_slash = f"{marker}/"
        if marker_with_slash in value:
            return value.split(marker_with_slash, 1)[1]
        if value.rstrip("/").endswith(marker):
            return "."
    return value


def relativize_project_paths(value: Any) -> Any:
    """Replace persisted project-root paths with repository-relative paths."""

    if isinstance(value, str):
        return _relativize_string(value)
    if isinstance(value, list):
        return [relativize_project_paths(item) for item in value]
    if isinstance(value, tuple):
        return tuple(relativize_project_paths(item) for item in value)
    if isinstance(value, dict):
        return {key: relativize_project_paths(item) for key, item in value.items()}
    return value
