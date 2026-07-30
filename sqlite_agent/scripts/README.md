# 脚本使用指南

脚本按数据准备、环境验证、SFT 和 RL 四个阶段组织。所有命令应从仓库
根目录运行：

```bash
export PYTHONPATH="$PWD/sqlite_agent:${PYTHONPATH:-}"
```

## 1. 准备数据

`data/` 提供从 Spider/CSpider 到可训练任务划分的完整流水线：

- `data/normalize_raw_datasets.py`：将原始 Spider/CSpider JSON 归一化为
  统一任务结构
- `data/inspect_raw_datasets.py`：检查任务数、数据库数、公共数据库和缺失字段
- `data/relativize_paths.py`：将任务中的机器绝对路径转换为项目相对路径
- `data/build_task_pool.py`：按 `(db_id, normalized_gold_sql)` 合并并去重
  Spider/CSpider 任务
- `data/cache_and_filter_task_pool.py`：执行 Gold SQL、缓存
  `gold_result`，并过滤无效或不适合训练的任务
- `data/make_splits.py`：按完整 `db_id` 将过滤后的任务池划分为
  `train/dev/final_eval`，并构造小型开发集冒烟子集
- `data/build_hard_eval.py`：从 dev split 构造英文困难 mini 评测集

完整下载和构造命令见 [`data/raw/README.md`](../../data/raw/README.md)。

## 2. 验证 SQLite 环境

```bash
python sqlite_agent/scripts/env/smoke_agent_env.py \
  --task-file data/splits/v2_db_seed42/dev_smoke.jsonl
```

该命令检查四个模型可见工具、数据库路径和 Gold Result verifier。
详细说明见 [`env/README.md`](env/README.md)。

## 3. 构造与训练 SFT

常用入口：

- `sft/build_sql_core.py`：从划分任务构造直接 SQL 核心样本
- `sft/collect_teacher_rollouts.py`：采集真实工具调用轨迹
- `sft/judge_rollout_audit.py`：审计 verifier 失败和可疑标签噪声
- `sft/build_rollout_buckets.py`：生成审计后的轨迹分桶
- `sft/build_sft_from_teacher_rollouts.py`：把保留轨迹转换为 SFT 样本
- `sft/train_sft_v2_lora.py`：训练 LoRA adapter
- `sft/evaluate_sft_v2_agent.py`：通过 Agent runtime 评测单个 checkpoint
- `sft/run_formal_sft_eval.py`：编排正式训练和固定步数评测
- `sft/cleanup_sft_run.py`：在结果确认后保留选定 checkpoint 和摘要
- `sft/inspect_sft_token_lengths.py`：检查 SFT 样本的 token 长度分布

正式入口：

```bash
python sqlite_agent/scripts/sft/run_formal_sft_eval.py --help
```

完整训练与评测命令见 [`sft/README.md`](sft/README.md)。

## 4. 评测 checkpoint

```bash
python sqlite_agent/scripts/sft/evaluate_sft_v2_agent.py --help
```

评测器会运行真实 Agent loop，而不是只计算 teacher-forcing loss。

## 5. 准备和运行 RL

- `rl/build_rl_smoke_tasks.py`：按难度分层构造训练和验证 prompt
- `rl/prepare_slime_data.py`：把任务转换为 Slime JSONL/Parquet 输入
- `rl/merge_lora_checkpoint.py`：把 SFT adapter 合并进基座模型
- `rl/run_rl_dryrun_hf.py`：执行轻量本地 reward/runtime 试运行
- `rl/run_slime_rl_smoke.sh`：在提供外部框架路径后启动 Slime GRPO

推荐先完成不更新参数的 dry-run：

```bash
python sqlite_agent/scripts/rl/run_rl_dryrun_hf.py --help
```

再按 [`data/rl/README.md`](../../data/rl/README.md) 准备 Slime 环境并启动训练。

## 6. 复现实验与消融

`archive/` 提供确定性冷启动、协议转换、机械轨迹增强和仅英文数据等对照
实验脚本。它们用于复现实验或构造消融组，不是默认训练入口；使用方式见
[`archive/README.md`](archive/README.md)。
