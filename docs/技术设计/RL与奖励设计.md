# RL 与奖励设计

## 训练闭环

正式 RL 使用 Slime 编排、SGLang rollout、Megatron actor 更新和 Ray 资源调度。每个 prompt 采样 4 条轨迹，SQLite Runtime 执行动作，GRPO 使用组内相对奖励更新策略。

Stage 2 记录的配置为 2,048 个训练 prompt、120 个验证 prompt、512 个 rollout，约 8,192 条训练轨迹。Actor 与 Rollout 使用 2+2 GPU，TP=2，并启用 optimizer CPU offload、activation recompute 和动态 batching。

## 奖励公式

```text
R = R_outcome + P_parse + P_budget + P_protocol
    + P_final_mismatch + P_steps
```

| 条件 | 奖励 / 惩罚 |
|---|---:|
| 完整结果值等价 | `+1.00` |
| SQL 可执行但结果错误 | `+0.20` |
| 已提交但不可执行 | `+0.05` |
| 解析失败 | `-0.30` |
| 超出步数 | `-0.10` |
| 协议无效 / 非标准 | `-0.20 / -0.05` |
| final mismatch | `-0.05` |
| 第 6 步后继续调用 | 每步 `-0.02` |
| 不安全 SQL | 最终 `-1.00` |

## final mismatch 与 0.75

final mismatch 不是“最终答案一定错误”，而是“提交行为与刚才验证过的行为不一致”。例如模型成功执行了 SQL A，却在 final 中提交 SQL B；或者没有成功执行任何 SQL 就直接提交 B。Runtime 记录 A，verifier 仍然重新执行并评分 B。

因此它与结果奖励是两个维度：

| 情况 | 结果项 | mismatch 约束 | 最终奖励（无其他惩罚） |
|---|---:|---:|---:|
| final=B，B 正确且 B 就是最后成功 SQL | `1.00` | `0` | `1.00` |
| final=B，B 正确但不等于最后成功 SQL | 正确项先封顶 `0.80` | `-0.05` | `0.75` |
| final=B，B 可执行但错误且发生 mismatch | `0.20` | `-0.05` | `0.15` |
| final=B，B 不可执行且发生 mismatch | `0.05` | `-0.05` | `0.00` |

`0.75` 的含义是：最终提交本身经完整执行验证为正确，所以保留大部分正确性信号；但模型没有遵守“先执行确认，再原样提交”的行为约束，所以不能拿满分。它不会因为 A 正确就奖励 B，真正决定正确性的是 final 中的 B。

## 结果与边界

记录中的最佳点为 rollout 349，平均奖励 0.8163、strict 73.3%、equivalent 78.3%；rollout 499 有小幅回落。曲线见 [`results/rl/stage2.validation.jsonl`](../../results/rl/stage2.validation.jsonl)。这些数值是由现有正式记录转录并关联到 W&B run `ari4f5ed`，不是仓库内的 W&B 原始 history 导出。

SFT full-dev 和 RL validation 不是同一任务集合，不能直接把 66.3% 与 78.3% 当作严格阶段增益。更严格的下一步是固定同一评测集和推理参数，重新跑 SFT 与各 RL checkpoint。
