# SFT 脚本

SFT 数据从任务真值池构造，而不是直接读取原始 Spider/CSpider 文件。

## 当前 Agent 协议

Agent 轨迹使用纯 JSON message content，不再使用 XML/HTML 风格标签。

- Assistant 工具调用：
  `{"type":"tool_call","name":"execute_sql","arguments":{"sql":"SELECT ..."}}`
- User 工具结果：
  `{"type":"tool_result","result":{"ok":true,...}}`
- Assistant 最终输出：
  `{"type":"final","final_sql":"SELECT ...","answer":"..."}`

`sql_core` 是独立的直接 SQL 模式：assistant content 就是 SQL 字符串。

当前构造器：

- `build_sql_core.py`：从划分任务构造确定性的直接 SQL 样本，不需要
  Teacher 模型
- `collect_teacher_rollouts.py`：让真实 Teacher 模型在 SQLite 环境中
  rollout，记录成功和失败轨迹，用于后续 SFT 与 repair 提取
- `judge_rollout_audit.py`：用 LLM judge 审计严格验证失败的轨迹，区分
  可疑标签不一致和真实模型错误
- `build_rollout_buckets.py`：合并 rollout 与审计结果，生成：
  - `strict_pass`
  - `strict_fail_true_error`
  - `strict_fail_suspect_label_mismatch`
  - `strict_fail_uncertain`
- `build_sft_from_teacher_rollouts.py`：把保留的 Teacher 轨迹转换为标准
  SFT 数据。由于部分历史来源早于 `json_v2`，其 XML 读取逻辑来自隔离的
  兼容模块

不要把每条任务机械展开为
`list_tables -> get_schema -> execute_sql(gold_sql)` 并作为主要 Agent
数据。这会让模型模仿固定路径，而不是根据真实环境选择动作。

## 历史冷启动混合数据

Teacher 轨迹引入前曾使用以下近似比例。这不是当前正式 V3 训练集，相关
生成产物已在 2026-07-10 清理。

当时建议的数据比例：

- 约 `55%` `sql_core`
- 约 `25%` `tool_trace_bootstrap`
- 约 `20%` `repair_missing_table`

在每条基础 `sql_core` 数据之上使用：

- `tool_trace_rate = 0.45`
- `repair_rate = 0.35`

最终混合比例通常接近 55 / 25 / 20。

确定性冷启动、XML 迁移、仅英文构造和机械 V3 增强脚本保存在
`sqlite_agent/scripts/archive/sft/` 中，仅在明确复现历史消融时使用。

```bash
python3 sqlite_agent/scripts/archive/sft/build_mixed_sft.py \
  --input data/splits/v2_db_seed42/train.jsonl \
  --output-jsonl data/sft/train_v2_mixed.jsonl \
  --output-parquet data/sft/train_v2_mixed.parquet \
  --manifest data/sft/train_v2_mixed.manifest.json
```

## 正式 V3 流程

正式运行使用相互独立的脚本：

1. `train_sft_v2_lora.py`：只负责连续 SFT 训练。首次启动时必须使用最终
   `--max-steps`，或者从 Trainer checkpoint 恢复，以保持完整学习率曲线。
2. `evaluate_sft_v2_agent.py`：只评测一个明确的 checkpoint/adapter 和
   一个明确的评测集。
3. `cleanup_sft_run.py`：在最终评测后清理训练目录，只保留选中的
   checkpoint 和结果摘要。

旧的 `run_sft_v2_segmented.py` 已删除，因为它可能在验证边界重置学习率
调度状态。

### 正式训练与评测调度器

`run_formal_sft_eval.py` 是正式编排入口。每次训练调用都保持完整的
`--max-steps`，通过 `--stop-at-step` 在固定位置暂停并执行验证。这样既能
保留 Trainer 的 optimizer 和学习率调度器状态，又能在固定 checkpoint
进行 Agent 评测。

命令示例：

```bash
python sqlite_agent/scripts/sft/run_formal_sft_eval.py \
  --model /path/to/Qwen2.5-Coder-3B-Instruct \
  --train-data data/sft/v3_real_json/sft_v3_real_json_5817.jsonl \
  --mini-dev data/eval/sft_v2_json/hard_mini_dev_en.jsonl \
  --fast-dev data/eval/sft_v2_json/fast_dev.jsonl \
  --full-dev data/eval/sft_v2_json/full_dev.jsonl \
  --output-dir checkpoints/qwen25_coder3b_sqlite_sft_v3_real_json_formal \
  --epochs 2 \
  --train-samples 5817 \
  --eval-every-steps 100 \
  --bf16 \
  --local-files-only \
  --wandb-project sqlite-agentic-rl-v2 \
  --wandb-run-name sft_v3_real_json_coder3b_formal
```
