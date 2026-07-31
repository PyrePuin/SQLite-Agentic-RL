# Agent 协议与运行循环

该目录定义模型与 SQLite 环境之间的交互协议，以及一个与模型后端无关的同步 rollout 循环。

| 文件 | 作用 |
|---|---|
| `protocol.py` | 定义 `json_v2` system prompt、工具调用、工具结果和 final 消息 |
| `parser.py` | 解析工具调用与 final，并分别记录“可解析”和“canonical” |
| `rollout.py` | 接收任意 `generate(messages) -> str` 函数，运行同步 Agent loop |

## 协议

Assistant 每轮只能输出一个 JSON 对象：

```json
{"type":"tool_call","name":"get_schema","arguments":{"table_names":["orders"]}}
```

成功执行 SQL 后提交：

```json
{"type":"final","final_sql":"SELECT ...","answer":"..."}
```

正式 parser 要求对象字段与 schema 一致。`extract_first_json_object()` 允许评测或 RL runtime 从过度生成文本中取出首个完整 JSON，同时把该轮标记为非 canonical，供指标与奖励使用。

## 使用同步 loop

```python
from sqlite_agent_pkg.agent.protocol import system_message
from sqlite_agent_pkg.agent.rollout import rollout

result = rollout(
    db_path="data/raw/spider/database/.../example.sqlite",
    messages=[system_message(), {"role": "user", "content": "How many rows?"}],
    generate=my_generate_function,
    max_steps=8,
)
```

`result` 包含完整 `messages`、已执行 `actions`、解析后的 `final` 和 `stop_reason`。生产 RL 使用异步 Slime loop，见 [`../rl/README.md`](../rl/README.md)。
