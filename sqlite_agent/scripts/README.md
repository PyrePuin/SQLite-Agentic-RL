# Scripts

Scripts are grouped by pipeline stage.

## data/

Dataset preparation and inspection scripts.

- `data/normalize_raw_datasets.py`: normalize raw Spider/CSpider JSON files into the V2 canonical raw schema.
- `data/inspect_raw_datasets.py`: inspect row counts, DB counts, common DBs, and missing fields.
- `data/build_task_pool.py`: merge Spider/CSpider raw files into one deduplicated task pool using `(db_id, normalized_gold_sql)`.
- `data/cache_and_filter_task_pool.py`: execute gold SQL, cache `gold_result`, and filter invalid or inconvenient tasks.
- `data/make_splits.py`: split the filtered task pool by whole `db_id` into train/dev/final_eval, plus a small dev smoke set.

## env/

SQLite agent environment checks.

- `env/smoke_agent_env.py`: smoke-test `list_tables`, `get_schema`, `preview_rows`, `execute_sql`, and strict verification on a real split task.

## sft/

Current SFT data construction, training, and evaluation scripts.

- `sft/build_sql_core.py`: build direct SQL core samples from split task files.
- `sft/collect_teacher_rollouts.py`: collect real tool-use trajectories.
- `sft/judge_rollout_audit.py`: audit verifier failures and possible label noise.
- `sft/build_rollout_buckets.py`: materialize audited rollout buckets.
- `sft/build_sft_from_teacher_rollouts.py`: convert retained traces into SFT rows.
- `sft/train_sft_v2_lora.py`: train a LoRA adapter.
- `sft/evaluate_sft_v2_agent.py`: evaluate one checkpoint through the runtime.
- `sft/run_formal_sft_eval.py`: orchestrate training and fixed-step evaluation.

## rl/

- `rl/build_rl_smoke_tasks.py`: construct difficulty-stratified train/validation prompts.
- `rl/prepare_slime_data.py`: convert tasks to Slime JSONL/Parquet input.
- `rl/merge_lora_checkpoint.py`: merge the SFT adapter into the base model.
- `rl/run_rl_dryrun_hf.py`: run a lightweight local reward/runtime dry-run.
- `rl/run_slime_rl_smoke.sh`: launch Slime GRPO after external paths are supplied.

## archive/

Historical and ablation-only dataset builders live under `archive/`. They are
retained for provenance, not recommended as formal pipeline entrypoints.
