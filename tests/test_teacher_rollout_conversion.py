from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROLLOUTS = PROJECT_ROOT / "data/teacher_rollouts/hard_teacher_v4pro_en_all_dedup_20260706.jsonl"
FORMAL_SFT = PROJECT_ROOT / "data/sft/v3_real_json/sft_v3_real_json_5817.jsonl"


def test_teacher_conversion_reproduces_formal_20260706_rows(tmp_path: Path) -> None:
    output = tmp_path / "teacher.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "sqlite_agent/scripts/sft/build_sft_from_teacher_rollouts.py",
            "--input",
            str(ROLLOUTS),
            "--output",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    generated = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    formal = [
        json.loads(line)
        for line in FORMAL_SFT.read_text(encoding="utf-8").splitlines()
        if '"variant":"teacher_agent_real_v3"' in line
    ]

    assert len(generated) == 331
    assert generated == formal
