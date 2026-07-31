# SQLite Agent Python 包

`sqlite_agent_pkg` 是项目各脚本共享的核心实现。它把协议、环境和奖励集中在一个包中，避免 Teacher、SFT 评测和 RL 各自定义不一致的工具或正确性口径。

## 模块边界

| 子模块 | 职责 |
|---|---|
| [`agent/`](agent/README.md) | JSON 协议、输出解析和同步 Agent loop |
| [`data/`](data/README.md) | `Task` 数据结构、JSONL 读写和数据库路径解析 |
| [`env/`](env/README.md) | 四个 SQLite 工具、只读 SQL 防护和执行结果验证 |
| [`rl/`](rl/README.md) | Reward、Slime 异步 Agent 和训练指标聚合 |
| [`compat/`](compat/README.md) | 读取历史 XML 监督数据的兼容层 |

## 一条轨迹的数据流

```text
Task
-> protocol 构造 messages
-> parser 解析模型 JSON
-> env 执行工具并返回 observation
-> Agent 继续调用工具或提交 final_sql
-> verifier 重跑 final_sql
-> reward/metrics 生成训练信号
```

包采用 `src` 等价布局，仓库根目录的 `pyproject.toml` 已将包目录配置为 `sqlite_agent/`。安装 editable 包后可直接导入：

```python
from sqlite_agent_pkg.data.task_schema import load_tasks
from sqlite_agent_pkg.env.sqlite_tools import execute_tool
from sqlite_agent_pkg.rl.reward import compute_sqlite_agent_reward
```
