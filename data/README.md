# 数据目录说明

`data/` 保存 SQLite Agentic RL 从原始任务到 SFT、评测和 RL 输入的完整数据链路。任务中的数据库路径统一使用仓库相对路径，便于在本地、训练服务器和 CI 环境之间迁移。

## 数据流

```text
Spider / CSpider 原始数据
        ↓ 归一化
raw/：统一任务与 SQLite 数据库
        ↓ 合并、去重、执行 Gold SQL、过滤
pool/：可执行的统一任务池
        ↓ 按完整 db_id 划分
splits/：train / dev / final_eval
        ├────────────→ teacher_rollouts/ → sft/
        ├────────────→ eval/
        └────────────→ rl/
```

## 目录组成

| 目录 | 作用 | 默认下游输入 |
|---|---|---|
| `raw/` | Spider 1.0、CSpider 1.0 的下载、归一化任务和 SQLite 数据库 | `pool/` |
| `pool/` | 合并中英文任务，按数据库和 SQL 去重，并缓存 Gold SQL 执行结果 | `task_pool.filtered.jsonl` |
| `splits/` | 按完整 `db_id` 划分训练、开发和最终保留评测集 | `v2_db_seed42/` |
| `teacher_rollouts/` | 困难英文候选池以及 Teacher 在真实 SQLite runtime 中生成的轨迹 | 正式 SFT 的 331 条真实轨迹 |
| `sft/` | SFT 基础版本、最终训练文件及审计信息 | `v3_real_json/sft_v3_real_json_5817.jsonl` |
| `eval/` | 从 dev 划分构造的 mini、fast、full 三档 Agent 评测集 | checkpoint 选择与误差分析 |
| `rl/` | Slime/RL runtime 使用的轻量 smoke/repro 任务集 | `train_tasks.jsonl`、`val_tasks.jsonl` |

每个子目录的具体文件、规模和重建方式见该目录内的 `README.md`。

## 当前正式输入

### SFT

- 训练集：`data/sft/v3_real_json/sft_v3_real_json_5817.jsonl`
- 规模：5,817 条
- 协议：`json_v2`
- 组成：5,486 条 V2 基础数据 + 331 条验证成功的真实 Teacher Agent 轨迹

### 评测

| 文件 | 行数 | 主要用途 |
|---|---:|---|
| `data/eval/mini_dev.jsonl` | 110 | 高频、低成本的英文困难评测 |
| `data/eval/fast_dev.jsonl` | 120 | 训练中间阶段的快速评测 |
| `data/eval/full_dev.jsonl` | 300 | 正式 checkpoint 比较与选择 |

`data/splits/v2_db_seed42/final_eval.jsonl` 是最终保留集，不参与 SFT 采样、超参数调整或 checkpoint 选择。

### RL

- 训练任务：`data/rl/train_tasks.jsonl`，768 条
- 验证任务：`data/rl/val_tasks.jsonl`，60 条

这套数据用于验证 Slime、Ray、Agent runtime、reward 和训练更新链路。正式 RL 实验可以从 train/dev split 重新构造更大的 prompt 集，不应把当前 768 条 smoke 数据描述成正式 2048 条训练集。

## 数据边界

- `raw/` 中的下载包、数据库和其他大体积上游数据遵循各自许可证与 `.gitignore` 规则。
- checkpoint、rollout 临时文件、Parquet、训练日志等运行产物应写入 `outputs/`、`logs/` 或 `checkpoints/`，不放入 `data/`。
- manifest 和 audit 用于记录构造来源、统计信息与质量检查；修改数据时必须同步更新。

所有命令均从仓库根目录执行：

```bash
cd SQLite-Agentic-RL
export PYTHONPATH="$PWD/sqlite_agent:${PYTHONPATH:-}"
```
