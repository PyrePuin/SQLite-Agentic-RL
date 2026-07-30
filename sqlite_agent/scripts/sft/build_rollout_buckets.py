from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def choose_bucket(row: dict[str, Any], audit_by_task: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any] | None]:
    task_id = str(row.get("task_id") or "")
    audit = audit_by_task.get(task_id)
    if row.get("success"):
        return "strict_pass", audit

    rollout = row.get("rollout") or {}
    final = rollout.get("final") or {}
    verify = row.get("verify") or {}
    stop_reason = rollout.get("stop_reason")
    pred_sql = final.get("final_sql") or final.get("sql") or ""

    if not pred_sql:
        if stop_reason == "parse_failed":
            return "protocol_failure", audit
        return "finalization_failure", audit

    if pred_sql and not verify.get("pred_executable", False):
        return "execution_failure", audit

    if audit is None:
        return "semantic_or_label_uncertain", None

    judge = audit.get("judge") or {}
    verdict = judge.get("verdict")
    if verdict == "prefer_prediction":
        return "label_or_translation_conflict", audit
    if verdict == "prefer_gold":
        return "semantic_error", audit
    if verdict == "both_bad":
        return "semantic_error", audit
    if verdict == "both_ok_but_different":
        return "equivalent_output", audit
    return "semantic_or_label_uncertain", audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge rollout rows and audit rows into training/eval buckets.")
    parser.add_argument("--rollouts", required=True)
    parser.add_argument("--audit")
    parser.add_argument("--output", required=True)
    parser.add_argument("--bucket-dir")
    parser.add_argument("--manifest")
    args = parser.parse_args()

    rollout_rows = iter_jsonl(Path(args.rollouts))
    audit_rows = iter_jsonl(Path(args.audit)) if args.audit else []
    audit_by_task = {str(row.get("task_id") or ""): row for row in audit_rows}

    merged_rows: list[dict[str, Any]] = []
    bucketed: dict[str, list[dict[str, Any]]] = {
        "strict_pass": [],
        "protocol_failure": [],
        "finalization_failure": [],
        "execution_failure": [],
        "semantic_error": [],
        "label_or_translation_conflict": [],
        "equivalent_output": [],
        "semantic_or_label_uncertain": [],
    }
    counts = Counter()

    for row in rollout_rows:
        bucket, audit = choose_bucket(row, audit_by_task)
        merged = dict(row)
        merged["bucket"] = bucket
        if audit is not None:
            merged["audit"] = audit
        merged_rows.append(merged)
        bucketed[bucket].append(merged)
        counts[bucket] += 1

    output_path = Path(args.output)
    write_jsonl(output_path, merged_rows)

    bucket_outputs: dict[str, str] = {}
    if args.bucket_dir:
        bucket_dir = Path(args.bucket_dir)
        for bucket, rows in bucketed.items():
            bucket_path = bucket_dir / f"{bucket}.jsonl"
            write_jsonl(bucket_path, rows)
            bucket_outputs[bucket] = str(bucket_path)

    manifest = {
        "rollouts": args.rollouts,
        "audit": args.audit,
        "rows": len(merged_rows),
        "bucket_counts": dict(counts),
        "output": str(output_path),
        "bucket_outputs": bucket_outputs,
    }
    if args.manifest:
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
