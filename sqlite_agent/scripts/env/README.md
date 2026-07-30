# 环境检查脚本

`smoke_agent_env.py` 在真实划分任务上运行 SQLite Agent 工具和 verifier，
适合在训练或评测前检查数据库路径、工具协议与结果验证。

## 使用方式

从仓库根目录执行：

```bash
python sqlite_agent/scripts/env/smoke_agent_env.py \
  --task-file data/splits/v2_db_seed42/dev_smoke.jsonl
```

命令成功时会完成一次表发现、schema 查询、行预览、SQL 执行和 Gold
Result 验证。

## 模型可见工具

Agent runtime 只向模型暴露四个工具：

- `list_tables()`
- `get_schema(table_names)`
- `preview_rows(table_name, limit)`
- `execute_sql(sql)`

SQL 安全检查在 `sqlite_agent_pkg.env.sql_guard` 中由环境侧执行，不作为
模型可调用工具暴露。

如果 smoke 失败，优先检查：

1. 任务中的 `db_path` 是否相对于仓库根目录可解析；
2. 对应 `.sqlite` 文件是否存在；
3. `PYTHONPATH` 是否包含 `$PWD/sqlite_agent`；
4. SQL 是否触发只读限制或超时。
