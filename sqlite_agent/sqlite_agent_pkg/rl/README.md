# RL Runtime、奖励与指标

该目录把 SQLite Agent 接入 Slime 的在线采样接口，并将最终执行结果转换为 GRPO 使用的标量奖励。

| 文件 | 作用 |
|---|---|
| `slime_agent.py` | 异步调用 SGLang、执行工具、维护 token/loss mask，并生成轨迹 |
| `reward.py` | 重新执行 `final_sql`，计算结果奖励、协议惩罚和行为惩罚 |
| `slime_metrics.py` | 汇总 rollout/eval 的奖励、正确率、可执行率和协议指标 |

## 关键约束

- 模型生成的 assistant action token 使用 `loss_mask=1`；环境 observation 使用 `loss_mask=0`；
- Gold SQL/Result 只放在 sample metadata 与 reward label，不渲染进模型 prompt；
- `final_sql` 由 verifier 在完整结果上重新执行，不能用截断 observation 伪造正确性；
- 正确结果是主要奖励，协议、超步数和 finalization 是约束项。

准备 Slime 输入：

```bash
python sqlite_agent/scripts/rl/prepare_slime_data.py \
  --tasks data/rl/train_tasks.jsonl \
  --output-jsonl outputs/rl/train.jsonl \
  --output-parquet outputs/rl/train.parquet
```

本地 dry-run 和正式启动方式见 [`../../scripts/rl/README.md`](../../scripts/rl/README.md)。奖励公式、GRPO 数据流与 reward hacking 分析见 [`../../../docs/RL模块面试学习笔记.md`](../../../docs/RL模块面试学习笔记.md)。
