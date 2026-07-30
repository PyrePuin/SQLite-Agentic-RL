from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_hard_eval_defaults_rebuild_mini_without_sidecar_manifest(
    tmp_path: Path,
) -> None:
    output = tmp_path / "mini_dev.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "sqlite_agent/scripts/data/build_hard_eval.py",
            "--output",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    summary = json.loads(result.stdout)
    assert summary["target"] == 120
    assert summary["rows"] == 110
    assert output.exists()
    assert not output.with_suffix(".manifest.json").exists()
