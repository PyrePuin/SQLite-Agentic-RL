from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

torch: Any = None


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
                if limit is not None and len(rows) >= limit:
                    break
    return rows


def render_message(message: dict[str, Any]) -> str:
    role = str(message["role"]).strip().capitalize()
    return f"{role}:\n{message['content']}\n\n"


class FormalMessagesDataset:
    def __init__(self, rows: list[dict[str, Any]], tokenizer: Any, max_length: int):
        self.rows = rows
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.rows)

    def _append(self, input_ids: list[int], labels: list[int], text: str, train: bool) -> None:
        ids = self.tokenizer(text, add_special_tokens=False).input_ids
        input_ids.extend(ids)
        labels.extend(ids if train else [-100] * len(ids))

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        messages = self.rows[idx]["messages"]
        input_ids: list[int] = []
        labels: list[int] = []
        if self.tokenizer.bos_token_id is not None:
            input_ids.append(self.tokenizer.bos_token_id)
            labels.append(-100)
        for message in messages:
            role = str(message.get("role"))
            self._append(input_ids, labels, render_message(message), train=role == "assistant")
        if self.tokenizer.eos_token_id is not None:
            input_ids.append(self.tokenizer.eos_token_id)
            labels.append(-100)
        input_ids = input_ids[: self.max_length]
        labels = labels[: self.max_length]
        attention_mask = [1] * len(input_ids)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
        }


class CausalCollator:
    def __init__(self, pad_token_id: int):
        self.pad_token_id = pad_token_id

    def __call__(self, features: list[dict[str, torch.Tensor]]) -> dict[str, torch.Tensor]:
        max_len = max(feature["input_ids"].shape[0] for feature in features)
        batch: dict[str, list[torch.Tensor]] = {"input_ids": [], "labels": [], "attention_mask": []}
        for feature in features:
            pad_len = max_len - feature["input_ids"].shape[0]
            batch["input_ids"].append(torch.nn.functional.pad(feature["input_ids"], (0, pad_len), value=self.pad_token_id))
            batch["labels"].append(torch.nn.functional.pad(feature["labels"], (0, pad_len), value=-100))
            batch["attention_mask"].append(torch.nn.functional.pad(feature["attention_mask"], (0, pad_len), value=0))
        return {key: torch.stack(value) for key, value in batch.items()}


def main() -> None:
    global torch
    parser = argparse.ArgumentParser(description="LoRA SFT for SQLite Agentic RL V2 JSON messages JSONL.")
    parser.add_argument("--model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    parser.add_argument("--train-data", default="data/sft/v2_json/sft_v2_json_5486.jsonl")
    parser.add_argument("--output-dir", default="checkpoints/qwen25_coder3b_sqlite_sft_v2_json")
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--max-steps", type=int, default=626)
    parser.add_argument("--stop-at-step", type=int, help="Stop training after this global step while keeping max_steps as the full schedule length.")
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--warmup-ratio", type=float, default=0.03)
    parser.add_argument("--lr-scheduler-type", default="cosine")
    parser.add_argument("--max-grad-norm", type=float, default=1.0)
    parser.add_argument("--lora-rank", type=int, default=32)
    parser.add_argument("--lora-alpha", type=int, default=64)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--init-adapter")
    parser.add_argument("--resume-from-checkpoint")
    parser.add_argument("--logging-steps", type=int, default=10)
    parser.add_argument("--save-steps", type=int, default=100)
    parser.add_argument("--save-total-limit", type=int, default=8)
    parser.add_argument("--wandb-project")
    parser.add_argument("--wandb-run-name")
    parser.add_argument("--wandb-run-id")
    parser.add_argument("--wandb-resume", default="allow")
    parser.add_argument("--bf16", action="store_true")
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()

    import torch as torch_module
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainerCallback, TrainingArguments

    torch = torch_module

    if args.wandb_project:
        os.environ.setdefault("WANDB_PROJECT", args.wandb_project)
        if args.wandb_run_name:
            os.environ.setdefault("WANDB_NAME", args.wandb_run_name)
        if args.wandb_run_id:
            os.environ.setdefault("WANDB_RUN_ID", args.wandb_run_id)
            os.environ.setdefault("WANDB_RESUME", args.wandb_resume)

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True, local_files_only=args.local_files_only)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    rows = read_jsonl(Path(args.train_data), args.max_samples)
    dataset = FormalMessagesDataset(rows, tokenizer, args.max_length)
    dtype = torch.bfloat16 if args.bf16 else torch.float16
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=dtype,
        device_map="auto",
        trust_remote_code=True,
        local_files_only=args.local_files_only,
    )
    model.gradient_checkpointing_enable()
    model.config.use_cache = False

    if args.init_adapter:
        model = PeftModel.from_pretrained(model, args.init_adapter, is_trainable=True)
    else:
        lora = LoraConfig(
            r=args.lora_rank,
            lora_alpha=args.lora_alpha,
            lora_dropout=args.lora_dropout,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        )
        model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    training_args = TrainingArguments(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        max_steps=args.max_steps,
        learning_rate=args.learning_rate,
        warmup_ratio=args.warmup_ratio,
        lr_scheduler_type=args.lr_scheduler_type,
        max_grad_norm=args.max_grad_norm,
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        save_total_limit=args.save_total_limit,
        bf16=args.bf16,
        fp16=not args.bf16,
        report_to=["wandb"] if args.wandb_project else [],
        run_name=args.wandb_run_name,
        remove_unused_columns=False,
        gradient_checkpointing=True,
    )
    callbacks = []
    if args.stop_at_step is not None:
        class StopAtStepCallback(TrainerCallback):
            def on_step_end(self, args_: Any, state: Any, control: Any, **kwargs: Any) -> Any:
                if state.global_step >= args.stop_at_step:
                    control.should_training_stop = True
                return control

        callbacks.append(StopAtStepCallback())

    if args.wandb_project:
        class WandbTrainStepCallback(TrainerCallback):
            def on_train_begin(self, args: Any, state: Any, control: Any, **kwargs: Any) -> None:
                try:
                    import wandb

                    if wandb.run is not None:
                        wandb.define_metric("train/global_step")
                        wandb.define_metric("train/*", step_metric="train/global_step")
                except Exception:
                    return

            def on_log(self, args: Any, state: Any, control: Any, logs: dict[str, Any] | None = None, **kwargs: Any) -> None:
                if logs is None:
                    return
                logs["train/global_step"] = state.global_step
                for key in ("loss", "grad_norm", "learning_rate", "epoch"):
                    if key in logs:
                        logs[f"train/{key}"] = logs[key]

        callbacks.append(WandbTrainStepCallback())

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=CausalCollator(tokenizer.pad_token_id),
        callbacks=callbacks,
    )
    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    completed_step = int(trainer.state.global_step)
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    exact_checkpoint_dir = Path(args.output_dir) / f"checkpoint-{completed_step}"
    trainer.save_model(str(exact_checkpoint_dir))
    tokenizer.save_pretrained(exact_checkpoint_dir)

    summary = {
        "model": args.model,
        "train_data": args.train_data,
        "samples": len(rows),
        "max_steps": args.max_steps,
        "stop_at_step": args.stop_at_step,
        "completed_step": completed_step,
        "max_length": args.max_length,
        "per_device_train_batch_size": args.per_device_train_batch_size,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "effective_batch_size": args.per_device_train_batch_size * args.gradient_accumulation_steps,
        "learning_rate": args.learning_rate,
        "lora_rank": args.lora_rank,
        "lora_alpha": args.lora_alpha,
        "lora_dropout": args.lora_dropout,
        "output_dir": args.output_dir,
        "resume_from_checkpoint": args.resume_from_checkpoint,
    }
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    (Path(args.output_dir) / "sft_v2_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
