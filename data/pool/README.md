# Unified Task Pool

This directory is the bridge between raw datasets and training/evaluation data.

The pool merges Spider and CSpider into deduplicated bottom-level SQL tasks. Spider and CSpider often contain the same task in English and Chinese, so the pool is deduplicated by:

```text
(db_id, normalized_gold_sql)
```

## Main File To Use

Use this file for the next stage:

```text
task_pool.filtered.jsonl
```

It contains tasks whose gold SQL was executed successfully and passed first-stage filters.

Current scale:

- filtered tasks: 7586
- DBs: 206
- paired English/Chinese tasks: 2759
- Chinese-only tasks: 3641
- English-only tasks: 1186

Filtering rules used in the current build:

- SQL must be readonly `SELECT` / `WITH`.
- gold SQL must execute successfully in local SQLite.
- result row count must be `<= 500`.
- SQL length must be `<= 1200`.
- execution time must be `<= 5.0` seconds.

Current dropped tasks:

- `too_many_rows`: 48
- `gold_exec_error`: 3

## Manifests

- `task_pool.raw.manifest.json`: statistics before execution/filtering.
- `task_pool.filter.manifest.json`: execution and filtering statistics.

## Intermediate Files

The `intermediate/` directory contains audit artifacts, not the default downstream input.

- `intermediate/task_pool.raw.jsonl`: deduplicated pool before gold execution.
- `intermediate/task_pool.with_gold.jsonl`: pool after gold execution, including dropped tasks and filter reasons.

Keep these while the data policy is still changing. They are useful for auditing filter decisions, but SFT/RL builders should use `task_pool.filtered.jsonl` by default.

## Row Shape

Each row contains fields like:

```json
{
  "pool_id": "pool_000001",
  "db_id": "aan_1",
  "db_path": "/absolute/path/to/db.sqlite",
  "question_en": null,
  "question_zh": "我们有多少作者？",
  "gold_sql": "SELECT count(*) FROM Author",
  "gold_result": {
    "ok": true,
    "columns": ["count(*)"],
    "rows": [[21486]],
    "row_count": 1,
    "canonical_hash": "..."
  },
  "gold_tables": ["Author"],
  "difficulty": {
    "num_tables": 1,
    "has_join": false,
    "has_group_by": false,
    "has_nested_query": false,
    "has_set_op": false,
    "sql_length": 27
  },
  "answer_spec": {
    "mode": "strict",
    "order_sensitive": false,
    "duplicate_sensitive": true
  },
  "sources": [
    {
      "task_id": "cspider_test_...",
      "source": "cspider",
      "language": "zh",
      "question": "..."
    }
  ]
}
```

## Rebuild Commands

From the project root:

```bash
python3 sqlite_agent/scripts/data/build_task_pool.py \
  --input data/raw/spider/tasks_all.jsonl \
  --input data/raw/cspider/tasks_train.jsonl \
  --input data/raw/cspider/tasks_dev.jsonl \
  --input data/raw/cspider/tasks_test.jsonl \
  --output data/pool/intermediate/task_pool.raw.jsonl \
  --manifest data/pool/task_pool.raw.manifest.json

python3 sqlite_agent/scripts/data/cache_and_filter_task_pool.py \
  --input data/pool/intermediate/task_pool.raw.jsonl \
  --with-gold-output data/pool/intermediate/task_pool.with_gold.jsonl \
  --filtered-output data/pool/task_pool.filtered.jsonl \
  --manifest data/pool/task_pool.filter.manifest.json \
  --max-rows 500 \
  --max-sql-length 1200 \
  --timeout-sec 5.0
```
