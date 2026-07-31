# RL 脚本使用指南

该目录覆盖 RL prompt 构造、SFT 模型合并、Runtime dry-run 和 Slime GRPO 启动。

| 脚本 | 作用 |
|---|---|
| `build_rl_smoke_tasks.py` | 按难度与空结果比例，从 train/dev 构造 RL 任务 |
| `prepare_slime_data.py` | 转换为 Slime 使用的 JSONL/Parquet，Gold 仅进入 metadata/label |
| `merge_lora_checkpoint.py` | 将 PEFT LoRA adapter 合并进 Hugging Face 基座 |
| `run_rl_dryrun_hf.py` | 用本地 HF 模型检查采样、工具、reward 和组内奖励方差 |
| `run_slime_rl_smoke.sh` | 启动 Ray、SGLang、Megatron 与 Slime 训练作业 |

## 推荐使用顺序

先运行小规模 dry-run：

```bash
python sqlite_agent/scripts/rl/run_rl_dryrun_hf.py --help
```

再将 LoRA 合并为完整 HF 模型：

```bash
python sqlite_agent/scripts/rl/merge_lora_checkpoint.py \
  --base-model /path/to/Qwen2.5-Coder-3B-Instruct \
  --adapter /path/to/checkpoint-600 \
  --output outputs/models/sqlite-sft-merged \
  --local-files-only
```

Slime 训练还需要把 HF 模型转换为其 Megatron checkpoint 格式，并设置 `SLIME_ROOT`、`MEGATRON_ROOT`、`MERGED_HF` 和 `MEGATRON_CKPT`。正式 4 卡启动示例见仓库根 [`README.md`](../../../README.md#6-启动-slime-grpo)。

仓库内 `data/rl/train_tasks.jsonl`（768）和 `val_tasks.jsonl`（60）用于 smoke/repro；正式 Stage 2 的 2048/120 数据应按根 README 的构造命令生成，不要混用两套统计口径。
