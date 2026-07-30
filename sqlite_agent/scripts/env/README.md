# 环境检查脚本

- `smoke_agent_env.py`：在一条真实划分任务上运行四工具 SQLite 环境。

V2 有意只保留四个模型可见工具：

- `list_tables()`
- `get_schema(table_names)`
- `preview_rows(table_name, limit)`
- `execute_sql(sql)`

SQL 安全检查在 `sqlite_agent_pkg.env.sql_guard` 中由环境侧执行，不作为
模型可调用工具暴露。
