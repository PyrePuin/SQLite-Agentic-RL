# Data Splits

Splits are made after `data/pool/task_pool.filtered.jsonl`.

The important policy is that train/dev/final_eval are split by whole `db_id`, not by individual question. This prevents the same SQLite database from leaking across training and evaluation.

## Current Split

Use:

```text
v2_db_seed42/
```

Files:

- `train.jsonl`: training pool for SFT data construction and later RL prompt construction.
- `dev.jsonl`: validation pool for model selection, debugging, and regular evaluation.
- `final_eval.jsonl`: held-out final evaluation pool. Do not use this for prompt tuning, SFT sampling choices, RL hyperparameters, or checkpoint selection.
- `dev_smoke.jsonl`: small dev subset for fast parser/tool/eval smoke tests.
- `split_manifest.json`: split statistics, DB assignment, and overlap checks.

Current scale:

| split | rows | dbs |
| --- | ---: | ---: |
| train | 6069 | 134 |
| dev | 761 | 36 |
| final_eval | 756 | 36 |
| dev_smoke | 72 | 36 |

`split_manifest.json` reports no DB overlap between train/dev/final_eval.

## Language Sampling Policy

The split files are bottom-level tasks. Many rows contain both `question_zh` and `question_en`, but the split itself does not decide which language to train on.

For SFT builders, use Chinese as the main distribution and English as auxiliary grounding:

- Overall target: roughly 80% Chinese CSpider-style questions, 20% English Spider-style questions.
- For paired tasks, default to the Chinese question.
- Add or sample the English version for only about 20% to 25% of paired tasks.
- Do not duplicate every paired task into both Chinese and English examples.

This keeps the final agent close to the target setting: Chinese user questions, English table/column names, English SQLite errors, and Chinese system/tool instructions.

## Rebuild

From the project root:

```bash
python3 sqlite_agent/scripts/data/make_splits.py \
  --input data/pool/task_pool.filtered.jsonl \
  --output-dir data/splits/v2_db_seed42 \
  --seed 42 \
  --train-frac 0.80 \
  --dev-frac 0.10 \
  --smoke-per-db 2 \
  --smoke-max-rows 128
```
