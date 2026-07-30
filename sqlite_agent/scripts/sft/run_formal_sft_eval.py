from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def checkpoint_step(path: Path) -> int | None:
    if not path.is_dir() or not path.name.startswith("checkpoint-"):
        return None
    try:
        return int(path.name.rsplit("-", 1)[1])
    except ValueError:
        return None


def latest_trainer_checkpoint(output_dir: Path) -> tuple[int, Path] | None:
    items: list[tuple[int, Path]] = []
    for path in output_dir.glob("checkpoint-*"):
        step = checkpoint_step(path)
        if step is not None and (path / "trainer_state.json").exists():
            items.append((step, path))
    return max(items, default=None, key=lambda item: item[0])


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def eval_cmd(
    args: argparse.Namespace,
    *,
    checkpoint: Path,
    tasks: str,
    output_dir: Path,
    name: str,
    step: int,
    prefix: str,
    max_tool_steps: int,
    wandb_run_id: str | None,
) -> list[str]:
    cmd = [
        sys.executable,
        "sqlite_agent/scripts/sft/evaluate_sft_v2_agent.py",
        "--base-model",
        args.model,
        "--adapter",
        str(checkpoint),
        "--tasks",
        tasks,
        "--output",
        str(output_dir / "rollouts" / f"{name}_step_{step:06d}.jsonl"),
        "--summary-output",
        str(output_dir / "rollouts" / f"{name}_step_{step:06d}.summary.json"),
        "--max-tool-steps",
        str(max_tool_steps),
        "--max-new-tokens",
        str(args.max_new_tokens),
        "--max-prompt-tokens",
        str(args.max_prompt_tokens),
        "--wandb-prefix",
        prefix,
        "--protocol",
        args.protocol,
    ]
    if args.local_files_only:
        cmd.append("--local-files-only")
    if args.wandb_project:
        cmd += ["--wandb-project", args.wandb_project, "--wandb-run-name", args.wandb_run_name]
        if wandb_run_id:
            cmd += ["--wandb-run-id", wandb_run_id, "--wandb-resume", "allow", "--wandb-step", str(step)]
    return cmd


def main() -> None:
    parser = argparse.ArgumentParser(description="Formal SFT train/eval orchestrator with continuous LR schedule.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--train-data", required=True)
    parser.add_argument("--mini-dev", required=True)
    parser.add_argument("--fast-dev", required=True)
    parser.add_argument("--full-dev", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--train-samples", type=int, required=True)
    parser.add_argument("--effective-batch-size", type=int, default=16)
    parser.add_argument("--eval-every-steps", type=int, default=100)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--lora-rank", type=int, default=32)
    parser.add_argument("--lora-alpha", type=int, default=64)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=16)
    parser.add_argument("--save-total-limit", type=int, default=10)
    parser.add_argument("--mini-max-tool-steps", type=int, default=8)
    parser.add_argument("--fast-max-tool-steps", type=int, default=8)
    parser.add_argument("--full-max-tool-steps", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--wandb-project")
    parser.add_argument("--wandb-run-name", required=True)
    parser.add_argument("--wandb-run-id")
    parser.add_argument("--protocol", choices=["json_v2"], default="json_v2")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--bf16", action="store_true")
    parser.add_argument("--skip-full-dev", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    epoch_steps = math.ceil(args.train_samples / args.effective_batch_size)
    total_steps = math.ceil(epoch_steps * args.epochs)
    targets = set(range(args.eval_every_steps, total_steps + 1, args.eval_every_steps))
    targets.update(epoch_steps * idx for idx in range(1, math.floor(args.epochs) + 1))
    targets.add(total_steps)
    ordered_targets = sorted(step for step in targets if 0 < step <= total_steps)

    wandb_run_id = args.wandb_run_id
    run_id_path = output_dir / "wandb_run_id.txt"
    if args.wandb_project:
        if wandb_run_id is None and run_id_path.exists():
            wandb_run_id = run_id_path.read_text(encoding="utf-8").strip()
        if wandb_run_id is None:
            wandb_run_id = uuid.uuid4().hex[:12]
        run_id_path.write_text(wandb_run_id + "\n", encoding="utf-8")

    history: list[dict[str, Any]] = []
    for target_step in ordered_targets:
        checkpoint = output_dir / f"checkpoint-{target_step}"
        mini_summary = output_dir / "rollouts" / f"mini_dev_step_{target_step:06d}.summary.json"
        if not (checkpoint / "trainer_state.json").exists():
            resume = latest_trainer_checkpoint(output_dir)
            train_cmd = [
                sys.executable,
                "sqlite_agent/scripts/sft/train_sft_v2_lora.py",
                "--model",
                args.model,
                "--train-data",
                args.train_data,
                "--output-dir",
                str(output_dir),
                "--max-steps",
                str(total_steps),
                "--stop-at-step",
                str(target_step),
                "--max-length",
                str(args.max_length),
                "--learning-rate",
                str(args.learning_rate),
                "--lora-rank",
                str(args.lora_rank),
                "--lora-alpha",
                str(args.lora_alpha),
                "--per-device-train-batch-size",
                str(args.per_device_train_batch_size),
                "--gradient-accumulation-steps",
                str(args.gradient_accumulation_steps),
                "--save-steps",
                str(args.eval_every_steps),
                "--save-total-limit",
                str(args.save_total_limit),
            ]
            if resume is not None:
                train_cmd += ["--resume-from-checkpoint", str(resume[1])]
            if args.bf16:
                train_cmd.append("--bf16")
            if args.local_files_only:
                train_cmd.append("--local-files-only")
            if args.wandb_project:
                train_cmd += ["--wandb-project", args.wandb_project, "--wandb-run-name", args.wandb_run_name]
                if wandb_run_id:
                    train_cmd += ["--wandb-run-id", wandb_run_id, "--wandb-resume", "allow"]
            run(train_cmd)

        if not mini_summary.exists():
            run(
                eval_cmd(
                    args,
                    checkpoint=checkpoint,
                    tasks=args.mini_dev,
                    output_dir=output_dir,
                    name="mini_dev",
                    step=target_step,
                    prefix="eval_mini",
                    max_tool_steps=args.mini_max_tool_steps,
                    wandb_run_id=wandb_run_id,
                )
            )

        item: dict[str, Any] = {"step": target_step, "checkpoint": str(checkpoint), "mini": read_json(mini_summary)}
        if target_step % epoch_steps == 0 or target_step == total_steps:
            fast_summary = output_dir / "rollouts" / f"fast_dev_step_{target_step:06d}.summary.json"
            if not fast_summary.exists():
                run(
                    eval_cmd(
                        args,
                        checkpoint=checkpoint,
                        tasks=args.fast_dev,
                        output_dir=output_dir,
                        name="fast_dev",
                        step=target_step,
                        prefix="eval_fast",
                        max_tool_steps=args.fast_max_tool_steps,
                        wandb_run_id=wandb_run_id,
                    )
                )
            item["fast"] = read_json(fast_summary)

        history.append(item)
        (output_dir / "formal_sft_eval_history.json").write_text(
            json.dumps({"epoch_steps": epoch_steps, "total_steps": total_steps, "targets": ordered_targets, "history": history}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.skip_full_dev:
        return

    ranked = sorted(
        history,
        key=lambda item: (
            float((item.get("fast") or item["mini"]).get("strict_or_equiv_pass", 0.0)),
            float((item.get("fast") or item["mini"]).get("finalization_rate", 0.0)),
        ),
        reverse=True,
    )[:2]
    for item in ranked:
        step = int(item["step"])
        checkpoint = Path(item["checkpoint"])
        full_summary = output_dir / "rollouts" / f"full_dev_step_{step:06d}.summary.json"
        if full_summary.exists():
            continue
        run(
            eval_cmd(
                args,
                checkpoint=checkpoint,
                tasks=args.full_dev,
                output_dir=output_dir,
                name="full_dev",
                step=step,
                prefix="eval_full",
                max_tool_steps=args.full_max_tool_steps,
                wandb_run_id=wandb_run_id,
            )
        )


if __name__ == "__main__":
    main()
