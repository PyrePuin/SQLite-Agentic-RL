# 脚本说明

脚本按流水线阶段组织。

## `data/`：数据处理

数据集准备与检查脚本：

- `data/normalize_raw_datasets.py`：将原始 Spider/CSpider JSON
  归一化为 V2 标准数据结构
- `data/inspect_raw_datasets.py`：检查任务数、数据库数、公共数据库和缺失字段
- `data/build_task_pool.py`：按 `(db_id, normalized_gold_sql)` 合并并去重
  Spider/CSpider 任务
- `data/cache_and_filter_task_pool.py`：执行 Gold SQL、缓存
  `gold_result`，并过滤无效或不适合训练的任务
- `data/make_splits.py`：按完整 `db_id` 将过滤后的任务池划分为
  `train/dev/final_eval`，并构造小型开发集冒烟子集

## `env/`：环境检查

- `env/smoke_agent_env.py`：在真实划分任务上检查 `list_tables`、
  `get_schema`、`preview_rows`、`execute_sql` 和严格结果验证

## `sft/`：监督微调

当前 SFT 数据构造、训练和评测脚本：

- `sft/build_sql_core.py`：从划分任务构造直接 SQL 核心样本
- `sft/collect_teacher_rollouts.py`：采集真实工具调用轨迹
- `sft/judge_rollout_audit.py`：审计 verifier 失败和可疑标签噪声
- `sft/build_rollout_buckets.py`：生成审计后的轨迹分桶
- `sft/build_sft_from_teacher_rollouts.py`：把保留轨迹转换为 SFT 样本
- `sft/train_sft_v2_lora.py`：训练 LoRA adapter
- `sft/evaluate_sft_v2_agent.py`：通过 Agent runtime 评测单个 checkpoint
- `sft/run_formal_sft_eval.py`：编排正式训练和固定步数评测

## `rl/`：强化学习

- `rl/build_rl_smoke_tasks.py`：按难度分层构造训练和验证 prompt
- `rl/prepare_slime_data.py`：把任务转换为 Slime JSONL/Parquet 输入
- `rl/merge_lora_checkpoint.py`：把 SFT adapter 合并进基座模型
- `rl/run_rl_dryrun_hf.py`：执行轻量本地 reward/runtime 试运行
- `rl/run_slime_rl_smoke.sh`：在提供外部框架路径后启动 Slime GRPO

## `archive/`：历史脚本

`archive/` 保存历史数据构造器和仅用于消融的脚本，以便追溯实验过程。
它们不是正式流水线入口。
