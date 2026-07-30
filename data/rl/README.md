# RL 任务数据

该目录保存用于验证 Slime Agentic RL 链路的轻量任务集。当前只有一套有效版本，因此文件直接放在 `data/rl/`，不再额外套一层 `smoke_v1_768/`。

## 文件说明

| 文件 | 规模 | 作用 |
|---|---:|---|
| `train_tasks.jsonl` | 768 条、91 个数据库 | RL smoke 训练 prompt，偏重中等和困难 SQL |
| `val_tasks.jsonl` | 60 条、22 个数据库 | 从英文困难 mini 评测集中采样的在线验证任务 |
| `manifest.json` | — | 记录随机种子、难度比例、来源、数据库覆盖和特征统计 |

这些文件保存任务和可验证的 Gold 信息，不保存模型 rollout、reward 日志或 checkpoint。运行产物应写入 `outputs/`、`logs/` 和 `checkpoints/`。

## 定位

当前 768/60 数据用于验证：

- Agent runtime 能否完成多轮工具调用；
- reward 能否区分协议错误、执行错误和结果正确性；
- Ray、SGLang、Slime 与训练进程能否贯通；
- 策略更新后能否正常评测和保存 checkpoint。

它属于 smoke/repro 数据，不应被描述成正式 2,048 条 RL 训练集。

## 重建当前数据

从仓库根目录执行：

```bash
python sqlite_agent/scripts/rl/build_rl_smoke_tasks.py \
  --train-source data/splits/v2_db_seed42/train.jsonl \
  --val-source data/eval/mini_dev.jsonl \
  --output-dir data/rl \
  --train-limit 768 \
  --val-limit 60 \
  --seed 768 \
  --medium-ratio 0.55 \
  --hard-ratio 0.35 \
  --simple-ratio 0.10 \
  --max-empty-ratio 0.12
```

脚本默认参数与当前数据一致。重建会覆盖本目录中的 JSONL 和 manifest，执行前应先确认 Git 工作区。

## 正式 RL 数据

正式实验可以从 `data/splits/v2_db_seed42/train.jsonl` 和 dev 数据重新生成更大的任务集，例如 2,048 条训练任务。正式实验的数据规模、随机种子和难度比例必须由单独 manifest 记录；不要直接改写本 README 中的 smoke 统计。
