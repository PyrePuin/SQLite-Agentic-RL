# SFT Scripts

SFT data is derived from the task truth pool, not directly from raw Spider/CSpider files.

## Current Agent Protocol

Agent trace rows use pure JSON message contents, not XML/HTML-style tag wrappers.

- Assistant tool call: `{"type":"tool_call","name":"execute_sql","arguments":{"sql":"SELECT ..."}}`
- User tool result: `{"type":"tool_result","result":{"ok":true,...}}`
- Assistant final: `{"type":"final","final_sql":"SELECT ...","answer":"..."}`

`sql_core` rows are a separate direct-SQL mode: the assistant content is the SQL string itself.

Current builders:

- `build_sql_core.py`: builds direct SQL samples from split task files. This is deterministic and does not require a teacher model.
- `collect_teacher_rollouts.py`: runs a real teacher model through the SQLite environment and records success/fail transcripts for later SFT and repair extraction.
- `judge_rollout_audit.py`: audits strict-fail rollout rows with an LLM judge and separates likely label mismatches from true model errors.
- `build_rollout_buckets.py`: merges rollout rows and audit rows into retained buckets:
  - `strict_pass`
  - `strict_fail_true_error`
  - `strict_fail_suspect_label_mismatch`
  - `strict_fail_uncertain`
- `build_sft_from_teacher_rollouts.py`: converts retained teacher traces into normalized SFT rows. Its XML reader comes from the isolated compatibility module because some historical source traces predate `json_v2`.

Do not mechanically expand every task into `list_tables -> get_schema -> execute_sql(gold_sql)` as the main agent dataset. That creates brittle imitation of a fixed path instead of real agent behavior.

## Historical Bootstrap Mix

The earlier pre-teacher bootstrap used the following approximation. It is not
the current formal V3 training set and its generated files were removed during
the 2026-07-10 cleanup.

Recommended row mix for the current phase:

- about `55%` `sql_core`
- about `25%` `tool_trace_bootstrap`
- about `20%` `repair_missing_table`

With the default script rates on top of one base `sql_core` row per task:

- `tool_trace_rate = 0.45`
- `repair_rate = 0.35`

The resulting blended row share is usually close to the 55 / 25 / 20 target.

The deterministic bootstrap, XML migration, English-only composition, and
mechanical V3 augmentation builders are retained under
`sqlite_agent/scripts/archive/sft/` for provenance. Rebuild them only for an
explicit historical ablation.

```bash
python3 sqlite_agent/scripts/archive/sft/build_mixed_sft.py \
  --input data/splits/v2_db_seed42/train.jsonl \
  --output-jsonl data/sft/train_v2_mixed.jsonl \
  --output-parquet data/sft/train_v2_mixed.parquet \
  --manifest data/sft/train_v2_mixed.manifest.json
```

## Formal V3 Workflow

Use separate scripts for formal runs:

1. `train_sft_v2_lora.py`: continuous SFT training only. It owns the full LR schedule and must be run with the final `--max-steps` from the beginning, or resumed from a Trainer checkpoint.
2. `evaluate_sft_v2_agent.py`: rollout evaluation only for one explicit checkpoint/adapter and one explicit eval set.
3. `cleanup_sft_run.py`: post-run cleanup after final eval, keeping only selected checkpoints and summaries.

The old `run_sft_v2_segmented.py` runner has been deleted because it could reset LR scheduling around validation boundaries.

### Formal train/eval scheduler

`run_formal_sft_eval.py` is the formal orchestrator. It keeps `--max-steps` equal to the full run length on every training call and uses `--stop-at-step` to pause for validation. This preserves Trainer optimizer and LR scheduler state while still evaluating at fixed checkpoints.

Example shape:

```bash
python sqlite_agent/scripts/sft/run_formal_sft_eval.py \
  --model /path/to/Qwen2.5-Coder-3B-Instruct \
  --train-data data/sft/v3_real_json/sft_v3_real_json_5817.jsonl \
  --mini-dev data/eval/sft_v2_json/hard_mini_dev_en.jsonl \
  --fast-dev data/eval/sft_v2_json/fast_dev.jsonl \
  --full-dev data/eval/sft_v2_json/full_dev.jsonl \
  --output-dir checkpoints/qwen25_coder3b_sqlite_sft_v3_real_json_formal \
  --epochs 2 \
  --train-samples 5817 \
  --eval-every-steps 100 \
  --bf16 \
  --local-files-only \
  --wandb-project sqlite-agentic-rl-v2 \
  --wandb-run-name sft_v3_real_json_coder3b_formal
```
