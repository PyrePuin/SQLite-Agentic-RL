# SQLite 环境与验证器

该目录实现 Agent 的可执行环境。模型只能看到四个业务工具；SQL 安全检查和结果验证由环境内部完成。

| 文件 | 作用 |
|---|---|
| `sqlite_tools.py` | 只读连接、四工具实现和统一 dispatcher |
| `sql_guard.py` | 限制为单条 `SELECT` / `WITH`，拒绝写操作和危险关键字 |
| `verifier.py` | 缓存完整 Gold Result，并比较预测 SQL 的执行结果 |

## 四个工具

- `list_tables`：列出业务表；
- `get_schema`：返回列、主键和外键；
- `preview_rows`：查看最多 20 行样例；
- `execute_sql`：执行只读 SQL，给模型的 observation 默认最多 100 行。

```python
from sqlite_agent_pkg.env.sqlite_tools import execute_tool

observation = execute_tool(
    "data/raw/spider/database/.../example.sqlite",
    {"name": "execute_sql", "arguments": {"sql": "SELECT count(*) FROM t"}},
)
```

## 正确性口径

`verify_sql()` 会重新执行最终 SQL，且使用完整结果而不是截断后的 observation：

- `header_exact + value_exact`：严格正确；
- `value_exact`：结果等价，允许列别名不同；
- 无 `ORDER BY` 语义时按多重集合比较，仍保留重复项数量；
- `order_sensitive=true` 时按行顺序比较。

环境冒烟命令见 [`../../scripts/env/README.md`](../../scripts/env/README.md)。
