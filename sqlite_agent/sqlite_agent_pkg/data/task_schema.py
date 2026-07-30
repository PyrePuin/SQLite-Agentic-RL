from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Task:
    task_id: str
    db_id: str
    question: str
    gold_sql: str
    db_path: Path
    table_names: list[str]
    gold_result: dict[str, Any] | None = None
    answer_spec: dict[str, Any] | None = None


def resolve_db_path(raw_path: str, base_dir: Path | None = None) -> Path:
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        if base_dir is None:
            return db_path
        candidate = base_dir / db_path
        if candidate.exists():
            return candidate
        for parent in [base_dir, *base_dir.parents]:
            candidate = parent / db_path
            if candidate.exists():
                return candidate
        return base_dir / db_path
    if db_path.exists():
        return db_path

    marker = "SQLite-Agentic-RL-V2/"
    text = str(db_path)
    if marker in text:
        suffix = text.split(marker, 1)[1]
        project_root = Path(__file__).resolve().parents[3]
        candidate = project_root / suffix
        if candidate.exists():
            return candidate
    return db_path


def task_from_row(row: dict[str, Any], base_dir: Path | None = None) -> Task:
    task_id = str(row.get("task_id") or row.get("id"))
    db_path = resolve_db_path(str(row["db_path"]), base_dir)
    return Task(
        task_id=task_id,
        db_id=str(row["db_id"]),
        question=str(row["question"]),
        gold_sql=str(row["gold_sql"]),
        db_path=db_path,
        table_names=list(row.get("table_names") or []),
        gold_result=row.get("gold_result"),
        answer_spec=row.get("answer_spec"),
    )


def task_to_row(task: Task) -> dict[str, Any]:
    row: dict[str, Any] = {
        "task_id": task.task_id,
        "db_id": task.db_id,
        "question": task.question,
        "gold_sql": task.gold_sql,
        "db_path": str(task.db_path),
        "table_names": task.table_names,
    }
    if task.gold_result is not None:
        row["gold_result"] = task.gold_result
    if task.answer_spec is not None:
        row["answer_spec"] = task.answer_spec
    return row


def load_tasks(path: str | Path) -> list[Task]:
    input_path = Path(path)
    tasks: list[Task] = []
    with input_path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                tasks.append(task_from_row(json.loads(line), input_path.resolve().parent))
    return tasks


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
