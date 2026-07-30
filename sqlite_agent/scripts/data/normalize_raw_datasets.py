from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def read_json_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        rows = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
        return rows
    with path.open(encoding="utf-8") as f:
        value = json.load(f)
    if isinstance(value, list):
        return value
    raise ValueError(f"Expected a JSON list or JSONL rows: {path}")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sqlite_path_for(db_root: Path, db_id: str) -> Path:
    candidates = [
        db_root / db_id / f"{db_id}.sqlite",
        db_root / db_id / f"{db_id}.db",
        db_root / f"{db_id}.sqlite",
        db_root / f"{db_id}.db",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"No SQLite file found for db_id={db_id} under {db_root}")


def load_table_names(path: Path | None) -> dict[str, list[str]]:
    if path is None:
        return {}
    rows = read_json_rows(path)
    return {str(row["db_id"]): list(row.get("table_names_original") or row.get("table_names") or []) for row in rows}


def normalize_rows(
    *,
    dataset: str,
    input_path: Path,
    db_root: Path,
    language: str,
    task_prefix: str,
    table_names_by_db: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    normalized = []
    for idx, row in enumerate(read_json_rows(input_path)):
        db_id = str(row["db_id"])
        question = row.get("question") or row.get("question_toks")
        if isinstance(question, list):
            question = " ".join(str(part) for part in question)
        gold_sql = row.get("gold_sql") or row.get("query")
        if not question or not gold_sql:
            raise ValueError(f"Missing question/query in row {idx} from {input_path}")
        task_id = str(row.get("task_id") or row.get("id") or f"{task_prefix}_{idx:06d}")
        table_names = row.get("table_names") or row.get("tables") or (table_names_by_db or {}).get(db_id, [])

        normalized.append(
            {
                "task_id": task_id if task_id.startswith(f"{task_prefix}_") else f"{task_prefix}_{task_id}",
                "dataset": dataset,
                "language": language,
                "db_id": db_id,
                "db_path": str(sqlite_path_for(db_root, db_id)),
                "question": str(question),
                "table_names": list(table_names),
                "gold_sql": str(gold_sql),
            }
        )
    return normalized


def copy_database_tree(source: Path, target: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize Spider/CSpider tasks into sqlite_agent/data/raw.")
    parser.add_argument("--dataset", required=True, choices=["spider", "cspider"])
    parser.add_argument("--input", required=True, help="Source task JSON or JSONL.")
    parser.add_argument("--db-root", required=True, help="Directory containing database subdirectories.")
    parser.add_argument("--output-dir", default="sqlite_agent/data/raw")
    parser.add_argument("--split", default="all")
    parser.add_argument("--task-prefix")
    parser.add_argument("--tables")
    parser.add_argument("--copy-databases", action="store_true")
    args = parser.parse_args()

    dataset = args.dataset
    language = "zh" if dataset == "cspider" else "en"
    task_prefix = args.task_prefix or ("cspider" if dataset == "cspider" else "spider")
    output_root = Path(args.output_dir) / dataset
    input_path = Path(args.input)
    db_root = Path(args.db_root)
    table_names_by_db = load_table_names(Path(args.tables)) if args.tables else {}
    normalized = normalize_rows(
        dataset=dataset,
        input_path=input_path,
        db_root=db_root,
        language=language,
        task_prefix=task_prefix,
        table_names_by_db=table_names_by_db,
    )

    if args.copy_databases:
        copy_database_tree(db_root, output_root / "database")

    tasks_path = output_root / f"tasks_{args.split}.jsonl"
    write_jsonl(tasks_path, normalized)
    db_ids = sorted({row["db_id"] for row in normalized})
    manifest = {
        "dataset": dataset,
        "language": language,
        "source_tasks": str(input_path),
        "source_db_root": str(db_root),
        "source_tables": args.tables,
        "output_tasks": str(tasks_path),
        "rows": len(normalized),
        "dbs": len(db_ids),
        "db_ids": db_ids,
    }
    manifest_path = output_root / f"manifest_{args.split}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tasks": str(tasks_path), "manifest": str(manifest_path), "rows": len(normalized)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
