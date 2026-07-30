from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_cache_and_filter_cli_resolves_package_from_repository_root() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "sqlite_agent/scripts/data/cache_and_filter_task_pool.py",
            "--help",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
