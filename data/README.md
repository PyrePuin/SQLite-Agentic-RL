# 数据目录说明

`data/` 保存 SQLite Agentic RL 从原始任务到 SFT、评测和 RL 输入的主要数据链路。任务池、数据划分和 Teacher 增量均提供可运行脚本；正式 SFT 文件已经随仓库发布，但历史基础 SFT 的全部构造过程并未整理成一条从零运行的一键流水线。任务中的数据库路径统一使用仓库相对路径，便于在本地、训练服务器和 CI 环境之间迁移。

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

## 推荐使用路径

如果希望理解并重跑可公开复现的数据处理链路：

1. 按 [`raw/README.md`](raw/README.md) 下载并归一化 Spider/CSpider。
2. 按 [`pool/README.md`](pool/README.md) 合并、执行并过滤任务池。
3. 按 [`splits/README.md`](splits/README.md) 生成 DB-level 数据划分。
4. 使用 [`sft/README.md`](sft/README.md) 中的正式训练集运行 SFT。
5. 使用 [`eval/README.md`](eval/README.md) 选择和评测 checkpoint。
6. 使用 [`rl/README.md`](rl/README.md) 验证 RL runtime 或构造正式 RL prompts。

这里的“重跑”边界是：可以从 Spider/CSpider 构造统一任务池与 DB-level split，也可以重跑公开 Teacher 轨迹的审计和 331 条增量转换；仓库没有提供从原始任务逐条重建历史 5,486 条基础 SFT 的全部构造脚本。训练复现应直接使用已经发布的 5,817 条正式文件。更具体的脚本顺序与命令见 [`sqlite_agent/scripts/data/README.md`](../sqlite_agent/scripts/data/README.md) 和 [`sqlite_agent/scripts/sft/README.md`](../sqlite_agent/scripts/sft/README.md)。

如果只希望运行训练与评测，可以直接使用下面列出的仓库内数据。

## 当前推荐输入

### SFT

- 训练集：`data/sft/v3_real_json/sft_v3_real_json_5817.jsonl`
- 规模：5,817 条
- 协议：`json_v2`
- 组成：5,486 条 V2 基础数据 + 331 条验证成功的真实 Teacher Agent 轨迹

七类样本的职责和数量见 [`sft/README.md`](sft/README.md)。

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

确认关键数据文件可读取：

```bash
wc -l \
  data/sft/v3_real_json/sft_v3_real_json_5817.jsonl \
  data/eval/mini_dev.jsonl \
  data/eval/fast_dev.jsonl \
  data/eval/full_dev.jsonl \
  data/rl/train_tasks.jsonl \
  data/rl/val_tasks.jsonl
```
