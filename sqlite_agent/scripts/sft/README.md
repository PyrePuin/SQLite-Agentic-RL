# SFT 构造、训练与评测

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

## 数据构造入口

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
  SFT 数据，并使用版本化 system prompt 保证结果可复现

不要把每条任务机械展开为
`list_tables -> get_schema -> execute_sql(gold_sql)` 并作为主要 Agent
数据。这会让模型模仿固定路径，而不是根据真实环境选择动作。

将成功 Teacher rollout 转成标准 SFT：

```bash
python sqlite_agent/scripts/sft/build_sft_from_teacher_rollouts.py \
  --input data/teacher_rollouts/hard_teacher_v4pro_en_all_dedup_20260706.jsonl \
  --output outputs/teacher_sft_331.jsonl \
  --manifest outputs/teacher_sft_331.manifest.json
```

对照实验和消融构造器见
[`../archive/README.md`](../archive/README.md)。

## 正式训练与评测流程

正式流程由三个职责独立的脚本组成：

1. `train_sft_v2_lora.py`：只负责连续 SFT 训练。首次启动时必须使用最终
   `--max-steps`，或者从 Trainer checkpoint 恢复，以保持完整学习率曲线。
2. `evaluate_sft_v2_agent.py`：只评测一个明确的 checkpoint/adapter 和
   一个明确的评测集。
3. `cleanup_sft_run.py`：在结果确认后保留选定 checkpoint 和评测摘要。

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
  --mini-dev data/eval/mini_dev.jsonl \
  --fast-dev data/eval/fast_dev.jsonl \
  --full-dev data/eval/full_dev.jsonl \
  --output-dir checkpoints/qwen25_coder3b_sqlite_sft_v3_real_json_formal \
  --epochs 2 \
  --train-samples 5817 \
  --effective-batch-size 16 \
  --eval-every-steps 100 \
  --max-length 2048 \
  --learning-rate 1e-4 \
  --bf16 \
  --local-files-only \
  --wandb-project sqlite-agentic-rl-v2 \
  --wandb-run-name sft_v3_real_json_coder3b_formal
```

### 单独评测 checkpoint

```bash
BASE_MODEL=/path/to/Qwen2.5-Coder-3B-Instruct

python sqlite_agent/scripts/sft/evaluate_sft_v2_agent.py \
  --base-model "$BASE_MODEL" \
  --adapter checkpoints/qwen25_coder3b_sqlite_sft_v3_real_json_formal/checkpoint-600 \
  --tasks data/eval/full_dev.jsonl \
  --output outputs/full_dev_checkpoint600.jsonl \
  --summary-output outputs/full_dev_checkpoint600.summary.json \
  --max-tool-steps 8 \
  --protocol json_v2
```

checkpoint 选择优先比较：

- `strict_or_equiv_pass`
- `sql_executable_rate`
- `finalization_rate`
- `canonical_protocol_valid_rate`
- `parse_failed_rate`
- `budget_exceeded_rate`

训练 loss 只反映监督目标拟合程度，不能替代真实 Agent rollout 评测。
