# 任务结构与路径处理

| 文件 | 作用 |
|---|---|
| `task_schema.py` | 定义不可变 `Task`，完成 JSONL 与对象互转，并解析数据库路径 |
| `path_utils.py` | 将历史机器绝对路径转换为仓库相对路径 |

## Task 字段

```text
task_id, db_id, question, gold_sql, db_path, table_names,
gold_result（可选）, answer_spec（可选）
```

加载任务：

```python
from sqlite_agent_pkg.data.task_schema import load_tasks

tasks = load_tasks("data/eval/mini_dev.jsonl")
print(tasks[0].question, tasks[0].db_path)
```

`resolve_db_path()` 优先使用现有相对路径；对于旧数据中的绝对路径，会尝试从项目目录标记之后的后缀重新定位。新写入的数据应始终保存仓库相对路径。
