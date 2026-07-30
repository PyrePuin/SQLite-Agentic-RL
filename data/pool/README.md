# 统一任务池

该目录连接原始数据和训练/评测数据。

任务池将 Spider 与 CSpider 合并成去重后的底层 SQL 任务。两套数据经常
包含同一任务的中英文版本，因此使用以下键去重：

```text
(db_id, normalized_gold_sql)
```

## 下游正式输入

后续阶段使用：

```text
task_pool.filtered.jsonl
```

其中只包含 Gold SQL 已成功执行并通过第一阶段过滤的任务。

当前规模：

- 过滤后任务：7,586 条
- 数据库：206 个
- 中英文配对任务：2,759 条
- 仅中文任务：3,641 条
- 仅英文任务：1,186 条

当前过滤规则：

- SQL 必须是只读 `SELECT` / `WITH`
- Gold SQL 必须能在本地 SQLite 中执行
- 结果行数必须 `<= 500`
- SQL 长度必须 `<= 1200`
- 执行时间必须 `<= 5.0` 秒

当前删除的任务：

- `too_many_rows`：48 条
- `gold_exec_error`：3 条

## 清单文件

- `task_pool.raw.manifest.json`：执行和过滤前的统计信息
- `task_pool.filter.manifest.json`：执行和过滤阶段的统计信息

## 中间文件

`intermediate/` 保存审计产物，不是默认下游输入：

- `intermediate/task_pool.raw.jsonl`：Gold 执行前的去重任务池
- `intermediate/task_pool.with_gold.jsonl`：Gold 执行后的完整任务池，包含
  被删除的任务及过滤原因

在数据策略仍可能变化时保留这些文件，便于复查过滤决定。SFT/RL 构造器
默认应使用 `task_pool.filtered.jsonl`。

## 数据行结构

每行包含以下字段：

```json
{
  "pool_id": "pool_000001",
  "db_id": "aan_1",
  "db_path": "data/raw/cspider/database/aan_1/aan_1.sqlite",
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

## 重建命令

从项目根目录执行：

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
