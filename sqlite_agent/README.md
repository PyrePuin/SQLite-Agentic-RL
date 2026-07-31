# SQLite Agent 核心代码

`sqlite_agent/` 包含项目可执行的 Agent runtime、SQLite 环境、训练奖励和各阶段脚本。数据文件放在仓库根目录的 `data/`，训练产物应写入 `outputs/`、`logs/` 或 `checkpoints/`。

## 目录结构

| 目录 | 作用 |
|---|---|
| `sqlite_agent_pkg/` | 可复用 Python 包：协议、Runtime、工具、验证器和 RL 接口 |
| `scripts/data/` | 原始数据归一化、任务池、Gold 缓存和 DB-level 划分 |
| `scripts/env/` | SQLite 工具与 verifier 冒烟检查 |
| `scripts/sft/` | Teacher 轨迹、SFT 构造、LoRA 训练和 Agent 评测 |
| `scripts/rl/` | RL 任务构造、模型合并、dry-run 和 Slime 启动 |
| `scripts/archive/` | 可复现实验与消融脚本，不是默认训练入口 |

## 安装

从仓库根目录执行：

```bash
python -m pip install -e '.[dev]'
export PYTHONPATH="$PWD/sqlite_agent:${PYTHONPATH:-}"
```

需要 SFT 依赖时改为：

```bash
python -m pip install -e '.[sft,dev]'
```

## 最短验证路径

先确认数据库、工具和 Gold verifier 可以正常工作：

```bash
python sqlite_agent/scripts/env/smoke_agent_env.py \
  --task-file data/splits/v2_db_seed42/dev_smoke.jsonl
```

运行测试：

```bash
pytest -q
```

训练入口与完整参数见 [`scripts/README.md`](scripts/README.md)，核心包的模块关系见 [`sqlite_agent_pkg/README.md`](sqlite_agent_pkg/README.md)。
