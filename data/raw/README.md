# 原始数据集

该目录用于在本地存放 SFT/RL 处理前的 benchmark 源文件和 SQLite
数据库。由于体积较大且受到上游许可证约束，原始下载内容不进入 Git。

## Spider

归一化后的 Spider 目录结构：

- `spider/source_all_tasks.jsonl`：源任务文件
- `spider/database/`：SQLite 数据库文件
- `spider/tasks_all.jsonl`：归一化后的 V2 任务文件，包含本地 `db_path`
- `spider/manifest_all.json`：归一化清单

当前规模：

- 7,000 条任务
- 140 个数据库
- 数据库目录约 875 MB

## CSpider

将下载后的 CSpider 文件放在：

```text
data/raw/cspider/source/
```

常见的原始文件结构为：

```text
train.json
dev.json
tables.json
database/
```

文件准备完成后执行归一化：

```bash
python sqlite_agent/scripts/data/normalize_raw_datasets.py \
  --dataset cspider \
  --input data/raw/cspider/source/train.json \
  --db-root data/raw/cspider/source/database \
  --output-dir data/raw \
  --split train
```

如果 CSpider 复用 Spider 的数据库文件而不单独提供数据库目录，请使用
`--db-root data/raw/spider/database`。

## 标准任务结构

每条归一化数据应包含：

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
