# 数据处理脚本运行指南

这些脚本负责把 Spider/CSpider 原始文件转换为可执行、可验证、按数据库隔离的任务划分。所有命令均从仓库根目录执行：

```bash
cd SQLite-Agentic-RL
python -m pip install -e '.[data,dev]'
export PYTHONPATH="$PWD/sqlite_agent:${PYTHONPATH:-}"
```

原始数据的下载地址、解压目录和许可证见 [`data/raw/README.md`](../../../data/raw/README.md)。

## 完整运行顺序

```text
normalize_raw_datasets.py
→ relativize_paths.py
→ inspect_raw_datasets.py
→ build_task_pool.py
→ cache_and_filter_task_pool.py
→ make_splits.py
→ build_hard_eval.py
```

## 1. 归一化 Spider/CSpider

`normalize_raw_datasets.py` 将上游 JSON、`tables.json` 和 SQLite 数据库整理为统一任务 JSONL。它只统一格式，不执行或验证 Gold SQL。

```bash
SPIDER_SOURCE=data/raw/spider/source/extracted/spider
CSPIDER_SOURCE=data/raw/cspider/source/extracted/full_CSpider/CSpider

python sqlite_agent/scripts/data/normalize_raw_datasets.py \
  --dataset spider \
  --input "$SPIDER_SOURCE/train_spider.json" \
  --db-root "$SPIDER_SOURCE/database" \
  --tables "$SPIDER_SOURCE/tables.json" \
  --output-dir data/raw \
  --split all \
  --task-prefix spider \
  --copy-databases

python sqlite_agent/scripts/data/normalize_raw_datasets.py \
  --dataset cspider \
  --input "$CSPIDER_SOURCE/train.json" \
  --db-root "$CSPIDER_SOURCE/database" \
  --tables "$CSPIDER_SOURCE/tables.json" \
  --output-dir data/raw \
  --split train \
  --task-prefix cspider_train

python sqlite_agent/scripts/data/normalize_raw_datasets.py \
  --dataset cspider \
  --input "$CSPIDER_SOURCE/dev.json" \
  --db-root "$CSPIDER_SOURCE/database" \
  --tables "$CSPIDER_SOURCE/tables.json" \
  --output-dir data/raw \
  --split dev \
  --task-prefix cspider_dev

python sqlite_agent/scripts/data/normalize_raw_datasets.py \
  --dataset cspider \
  --input "$CSPIDER_SOURCE/test_data/test.json" \
  --db-root "$CSPIDER_SOURCE/test_database" \
  --tables "$CSPIDER_SOURCE/test_data/tables_test.json" \
  --output-dir data/raw \
  --split test \
  --task-prefix cspider_test
```

主要输出：

```text
data/raw/spider/tasks_all.jsonl
data/raw/cspider/tasks_train.jsonl
data/raw/cspider/tasks_dev.jsonl
data/raw/cspider/tasks_test.jsonl
data/raw/*/manifest_*.json
```

如果 CSpider 与 Spider 共享数据库，可让任务路径指向已经复制的 Spider 数据库；否则应保证 `db_path` 指向实际存在的 `.sqlite` 文件。

## 2. 将绝对路径改为相对路径

归一化时需要访问本机数据库，因此 JSONL 里可能暂时出现绝对路径。进入任务池前运行：

```bash
python sqlite_agent/scripts/data/relativize_paths.py \
  data/raw/spider \
  data/raw/cspider
```

脚本会递归处理指定目录中的 JSON/JSONL，把项目根目录之前的机器路径去掉。新数据应保存成 `data/raw/...` 形式，避免迁移服务器后失效。

## 3. 检查原始任务

```bash
python sqlite_agent/scripts/data/inspect_raw_datasets.py \
  data/raw/spider/tasks_all.jsonl \
  data/raw/cspider/tasks_train.jsonl \
  data/raw/cspider/tasks_dev.jsonl \
  data/raw/cspider/tasks_test.jsonl
```

重点确认任务数、数据库数，以及缺失 question、SQL、`db_path` 字段的数量。该脚本检查的是数据结构与字段统计；数据库文件是否真正可访问，由链路末尾的 `smoke_agent_env.py` 验证。预期规模见 [`data/raw/README.md`](../../../data/raw/README.md)。

## 4. 合并并去重任务池

`build_task_pool.py` 按 `(db_id, normalized_gold_sql)` 合并 Spider/CSpider 的同义任务，同时保存中英文问题、来源 task id、Gold 涉及表和难度特征。

```bash
python sqlite_agent/scripts/data/build_task_pool.py \
  --input data/raw/spider/tasks_all.jsonl \
  --input data/raw/cspider/tasks_train.jsonl \
  --input data/raw/cspider/tasks_dev.jsonl \
  --input data/raw/cspider/tasks_test.jsonl \
  --output data/pool/intermediate/task_pool.raw.jsonl \
  --manifest data/pool/task_pool.raw.manifest.json
```

输出的 raw pool 只完成合并去重，还没有证明 Gold SQL 可执行。

## 5. 执行 Gold SQL、缓存结果并过滤

```bash
python sqlite_agent/scripts/data/cache_and_filter_task_pool.py \
  --input data/pool/intermediate/task_pool.raw.jsonl \
  --with-gold-output data/pool/intermediate/task_pool.with_gold.jsonl \
  --filtered-output data/pool/task_pool.filtered.jsonl \
  --manifest data/pool/task_pool.filter.manifest.json \
  --max-rows 500 \
  --max-sql-length 1200 \
  --timeout-sec 5
```

这个步骤会真实执行每条 Gold SQL，缓存完整 `gold_result`，并过滤非只读、执行失败、过慢、SQL 过长或结果过大的任务。正式结果为 7,586 条、206 个数据库；具体丢弃原因见 [`data/pool/README.md`](../../../data/pool/README.md)。

## 6. 按完整数据库划分

```bash
python sqlite_agent/scripts/data/make_splits.py \
  --input data/pool/task_pool.filtered.jsonl \
  --output-dir data/splits/v2_db_seed42 \
  --seed 42 \
  --train-frac 0.80 \
  --dev-frac 0.10 \
  --smoke-per-db 2 \
  --smoke-max-rows 128
```

输出：

```text
train.jsonl        6,069 条 / 134 DB
dev.jsonl            761 条 / 36 DB
final_eval.jsonl     756 条 / 36 DB
dev_smoke.jsonl       72 条 / 36 DB
split_manifest.json
```

脚本按完整 `db_id` 分配，最后会检查三个主划分是否存在数据库交集；检测到 overlap 时直接失败。

## 7. 构造困难 mini-dev

```bash
python sqlite_agent/scripts/data/build_hard_eval.py \
  --input data/splits/v2_db_seed42/dev.jsonl \
  --output data/eval/mini_dev.jsonl \
  --manifest outputs/data/mini_dev.manifest.json \
  --target 110 \
  --max-per-db 5 \
  --language-mode en_only \
  --seed 42
```

它根据多表、聚合、嵌套/集合操作、排序限制和 SQL 长度选择困难英文任务，并限制单个数据库的占比。

当前仓库只提供 `mini_dev` 的独立构造脚本；`fast_dev.jsonl` 和 `full_dev.jsonl` 已作为正式评测资产发布，但没有保留各自的一键重建脚本。三档评测集的定位和当前统计见 [`data/eval/README.md`](../../../data/eval/README.md)。

## 8. 最终检查

```bash
wc -l \
  data/pool/task_pool.filtered.jsonl \
  data/splits/v2_db_seed42/train.jsonl \
  data/splits/v2_db_seed42/dev.jsonl \
  data/splits/v2_db_seed42/final_eval.jsonl \
  data/eval/mini_dev.jsonl

python -m json.tool data/pool/task_pool.filter.manifest.json >/dev/null
python -m json.tool data/splits/v2_db_seed42/split_manifest.json >/dev/null

python sqlite_agent/scripts/env/smoke_agent_env.py \
  --task-file data/splits/v2_db_seed42/dev_smoke.jsonl
```

数据主链到此结束。SFT 数据组成与后续运行顺序见 [`../sft/README.md`](../sft/README.md)。
