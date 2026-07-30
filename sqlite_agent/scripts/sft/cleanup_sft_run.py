from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def parse_checkpoint_step(path: Path) -> int | None:
    if not path.name.startswith("checkpoint-"):
        return None
    try:
        return int(path.name.rsplit("-", 1)[1])
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean a SQLite Agentic RL SFT run directory after formal eval.")
    parser.add_argument("--run-dir", required=True, help="Checkpoint/output directory to clean.")
    parser.add_argument("--keep-checkpoints", nargs="*", type=int, default=[], help="Checkpoint steps to keep, e.g. 200 728.")
    parser.add_argument("--keep-final", action="store_true", help="Keep the run root adapter files.")
    parser.add_argument("--delete-partial-rollouts", action="store_true", help="Delete rollout JSONL files without matching summary JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned deletions without deleting.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        raise SystemExit(f"run dir does not exist: {run_dir}")

    keep = set(args.keep_checkpoints)
    deletions: list[Path] = []

    for path in run_dir.glob("checkpoint-*"):
        step = parse_checkpoint_step(path)
        if step is None:
            continue
        if step not in keep:
            deletions.append(path)

    if args.delete_partial_rollouts:
        rollouts = run_dir / "rollouts"
        if rollouts.exists():
            for path in rollouts.glob("*.jsonl"):
                summary = path.with_suffix(".summary.json")
                if not summary.exists():
                    deletions.append(path)

    if not args.keep_final:
        final_markers = ["adapter_model.safetensors", "adapter_config.json"]
        if any((run_dir / marker).exists() for marker in final_markers):
            print("final adapter files are present; pass --keep-final to document that they are intentionally retained")

    manifest = {
        "run_dir": str(run_dir),
        "keep_checkpoints": sorted(keep),
        "delete_partial_rollouts": args.delete_partial_rollouts,
        "dry_run": args.dry_run,
        "deletions": [str(path) for path in deletions],
    }
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

    if args.dry_run:
        return
    for path in deletions:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    (run_dir / "cleanup_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
