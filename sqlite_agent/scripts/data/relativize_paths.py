from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACKAGE_ROOT))

from sqlite_agent_pkg.data.path_utils import relativize_project_paths


SUPPORTED_SUFFIXES = {".json", ".jsonl"}


def iter_supported_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_dir():
            yield from (
                candidate
                for candidate in sorted(path.rglob("*"))
                if candidate.is_file() and candidate.suffix in SUPPORTED_SUFFIXES
            )
        elif path.suffix in SUPPORTED_SUFFIXES:
            yield path


def rewrite_json(path: Path) -> bool:
    original = json.loads(path.read_text(encoding="utf-8"))
    normalized = relativize_project_paths(original)
    if normalized == original:
        return False
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def rewrite_jsonl(path: Path) -> bool:
    temporary = path.with_name(f".{path.name}.tmp")
    changed = False
    try:
        with path.open("r", encoding="utf-8") as source, temporary.open("w", encoding="utf-8") as target:
            for line in source:
                if not line.strip():
                    continue
                original: Any = json.loads(line)
                normalized = relativize_project_paths(original)
                changed = changed or normalized != original
                target.write(json.dumps(normalized, ensure_ascii=False) + "\n")
        if changed:
            temporary.replace(path)
        else:
            temporary.unlink()
        return changed
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Rewrite persisted V2 project paths as repository-relative paths.")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    changed_files = []
    for path in iter_supported_files(args.paths):
        changed = rewrite_jsonl(path) if path.suffix == ".jsonl" else rewrite_json(path)
        if changed:
            changed_files.append(str(path))
    print(json.dumps({"changed_files": changed_files, "count": len(changed_files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
