# SFT V3 训练与评测

Updated: 2026-07-10

Run all commands from the V2 project root:

```bash
cd /path/to/SQLite-Agentic-RL-V2
export PYTHONPATH="$PWD/sqlite_agent:${PYTHONPATH:-}"
```

## Authoritative Inputs

```text
train:     data/sft/v3_real_json/sft_v3_real_json_5817.jsonl
mini-dev:  data/eval/sft_v2_json/hard_mini_dev_en.jsonl
fast-dev:  data/eval/sft_v2_json/fast_dev.jsonl
full-dev:  data/eval/sft_v2_json/full_dev.jsonl
model:     Qwen2.5-Coder-3B-Instruct
protocol:  json_v2
```

Do not use the deleted segmented runner or historical root-level continuation
wrappers. They could reset scheduler state around validation boundaries or
hard-code obsolete checkpoints and W&B run IDs.

## Formal Training

`run_formal_sft_eval.py` is the current orchestrator. It keeps the full
training horizon in `--max-steps` while using `--stop-at-step` internally to
pause at fixed evaluation boundaries, preserving optimizer and scheduler
state.

```bash
BASE_MODEL=/path/to/Qwen2.5-Coder-3B-Instruct

python sqlite_agent/scripts/sft/run_formal_sft_eval.py \
  --model "$BASE_MODEL" \
  --train-data data/sft/v3_real_json/sft_v3_real_json_5817.jsonl \
  --mini-dev data/eval/sft_v2_json/hard_mini_dev_en.jsonl \
  --fast-dev data/eval/sft_v2_json/fast_dev.jsonl \
  --full-dev data/eval/sft_v2_json/full_dev.jsonl \
  --output-dir checkpoints/qwen25_coder3b_sqlite_sft_v3_real_json_formal \
  --epochs 2 \
  --train-samples 5817 \
  --effective-batch-size 16 \
  --eval-every-steps 100 \
  --max-length 2048 \
  --learning-rate 1e-4 \
  --bf16 \
  --local-files-only \
  --wandb-project sqlite-agentic-rl-v2 \
  --wandb-run-name sft_v3_real_json_coder3b_formal
```

The formal run uses LoRA rank 32, alpha 64, dropout 0.05, micro-batch 1,
gradient accumulation 16, cosine scheduling, gradient checkpointing, and
`use_cache=false`.

## Explicit Checkpoint Evaluation

Training and evaluation remain separate entrypoints. To evaluate one adapter:

```bash
python sqlite_agent/scripts/sft/evaluate_sft_v2_agent.py \
  --base-model "$BASE_MODEL" \
  --adapter checkpoints/qwen25_coder3b_sqlite_sft_v3_real_json_formal/checkpoint-600 \
  --tasks data/eval/sft_v2_json/full_dev.jsonl \
  --output outputs/full_dev_checkpoint600.jsonl \
  --summary-output outputs/full_dev_checkpoint600.summary.json \
  --max-tool-steps 8 \
  --protocol json_v2 \
  --local-files-only
```

Checkpoint selection prioritizes:

```text
strict_or_equiv_pass
sql_executable_rate
finalization_rate
canonical_protocol_valid_rate
unrecoverable_parse_failed_rate
budget_exceeded_rate
```

Training loss alone is not sufficient because the project evaluates real
multi-turn tool use and final SQL execution.

## Current Result

The validated SFT candidate is checkpoint 600. On the 300-task full-dev set:

```text
strict_or_equiv_pass:           0.6633
strict_pass:                    0.4400
canonical_protocol_valid_rate:  0.9033
finalization_rate:              0.9433
sql_executable_rate:            0.9433
parse_failed_rate:              0.0267
budget_exceeded_rate:           0.0300
```

The remaining dominant error is executable but semantically incorrect SQL,
which motivated the subsequent GRPO stage.
