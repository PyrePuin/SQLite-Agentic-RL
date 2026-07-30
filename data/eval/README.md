# 评测数据

该目录保存从 `data/splits/v2_db_seed42/dev.jsonl` 构造的三档 Agent 评测集。它们用于训练过程中的 checkpoint 选择和错误分析，不包含最终保留的 `final_eval`。

## 三档评测集

| 文件 | 行数 | 数据库数 | 作用 |
|---|---:|---:|---|
| `mini_dev.jsonl` | 110 | 22 | 英文、多表和复杂 SQL 为主；用于最频繁的低成本 Agent 评测 |
| `fast_dev.jsonl` | 120 | 36 | 覆盖全部 dev 数据库；用于训练中间阶段的快速比较 |
| `full_dev.jsonl` | 300 | 36 | 更完整的 dev 子集；用于正式 checkpoint 比较和模型选择 |
| `manifest.json` | — | — | 三档数据的来源、语言、难度与规模统计 |

`fast_dev` 是 `full_dev` 的 120 条子集，但并非冗余：它用较低推理成本提供更频繁的稳定评测。`mini_dev` 是独立选择的英文困难切片，与 fast/full 的目标不同。

## 使用方式

正式 SFT 调度：

```bash
BASE_MODEL=/path/to/Qwen2.5-Coder-3B-Instruct

python sqlite_agent/scripts/sft/run_formal_sft_eval.py \
  --model "$BASE_MODEL" \
  --train-data data/sft/v3_real_json/sft_v3_real_json_5817.jsonl \
  --mini-dev data/eval/mini_dev.jsonl \
  --fast-dev data/eval/fast_dev.jsonl \
  --full-dev data/eval/full_dev.jsonl \
  --output-dir checkpoints/qwen25_coder3b_sqlite_sft \
  --train-samples 5817 \
  --wandb-run-name sqlite_sft_formal
```

单独评测 checkpoint：

```bash
BASE_MODEL=/path/to/Qwen2.5-Coder-3B-Instruct

python sqlite_agent/scripts/sft/evaluate_sft_v2_agent.py \
  --base-model "$BASE_MODEL" \
  --adapter checkpoints/qwen25_coder3b_sqlite_sft/checkpoint-600 \
  --tasks data/eval/full_dev.jsonl \
  --output outputs/full_dev.jsonl \
  --summary-output outputs/full_dev.summary.json \
  --protocol json_v2
```

评测必须运行完整 Agent runtime，让模型实际调用 SQLite 工具并提交 final SQL；不能只用 teacher forcing loss 代替。

重建英文困难 mini：

```bash
python sqlite_agent/scripts/data/build_hard_eval.py \
  --input data/splits/v2_db_seed42/dev.jsonl \
  --output data/eval/mini_dev.jsonl \
  --target 120 \
  --max-per-db 5 \
  --language-mode en_only \
  --seed 42
```

本目录使用统一的 `manifest.json` 描述三档评测集。调整采样策略后，应在
审计 JSONL 内容后同步更新该 manifest。

## 数据边界

`data/splits/v2_db_seed42/final_eval.jsonl` 不在本目录中，也不得用于：

- SFT 样本选择；
- prompt 或协议调试；
- RL 超参数选择；
- checkpoint 选择。
