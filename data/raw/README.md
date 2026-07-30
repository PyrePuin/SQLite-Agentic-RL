# Raw Datasets

This directory is the expected local location for benchmark source files and
SQLite databases before SFT/RL processing. Raw downloads are intentionally not
tracked because of their size and upstream licenses.

## Spider

Expected normalized Spider layout:

- `spider/source_all_tasks.jsonl`: source task file.
- `spider/database/`: SQLite database files.
- `spider/tasks_all.jsonl`: normalized V2 task file with local V2 `db_path` values.
- `spider/manifest_all.json`: normalization manifest.

Scale:

- 7000 tasks.
- 140 databases.
- database directory is about 875 MB.

## CSpider

Put downloaded CSpider files under:

```text
data/raw/cspider/source/
```

Expected raw files are usually similar to:

```text
train.json
dev.json
tables.json
database/
```

After files are available, normalize with:

```bash
python sqlite_agent/scripts/data/normalize_raw_datasets.py \
  --dataset cspider \
  --input data/raw/cspider/source/train.json \
  --db-root data/raw/cspider/source/database \
  --output-dir data/raw \
  --split train
```

If CSpider reuses Spider database files rather than shipping its own database directory, use `--db-root data/raw/spider/database`.

## Canonical Task Schema

Each normalized row should contain:

```json
{
  "task_id": "spider_000000",
  "dataset": "spider",
  "language": "en",
  "db_id": "department_management",
  "db_path": "data/raw/spider/database/department_management/department_management.sqlite",
  "question": "How many heads of the departments are older than 56 ?",
  "table_names": ["department", "head", "management"],
  "gold_sql": "SELECT count(*) FROM head WHERE age > 56"
}
```
