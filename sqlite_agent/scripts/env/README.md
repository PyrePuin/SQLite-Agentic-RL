# Env Scripts

- `smoke_agent_env.py`: run the four-tool SQLite environment on one real split task.

The V2 tool set is intentionally small:

- `list_tables()`
- `get_schema(table_names)`
- `preview_rows(table_name, limit)`
- `execute_sql(sql)`

SQL safety checks are server-side in `sqlite_agent_pkg.env.sql_guard`; they are not exposed as a model tool.
