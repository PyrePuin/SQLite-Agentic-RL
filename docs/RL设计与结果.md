# RL 设计与结果

## 目标

SFT 后的模型已经能够稳定输出工具协议并生成可执行 SQL。RL 阶段不再
主要修复格式，而是利用真实 SQLite 执行反馈，提高多轮探索、错误恢复和
最终结果正确率。

## Runtime 与采样

每条 prompt 在 Slime 中进入自定义 Agent runtime。模型最多进行 6 次工具
调用，环境执行 `list_tables`、`get_schema`、`preview_rows` 或
`execute_sql`，再把 observation 写回上下文。每个 prompt 采样 4 条轨迹，
由 GRPO 在组内计算相对优势。

正式 Stage 2 使用 2,048 个训练 prompt 和 120 个验证 prompt，难度比例为
10% simple、45% medium、45% hard。计划 512 个 rollout，共约 8,192 条
训练轨迹。

## Reward

SQLite verifier 是主要奖励来源：

| 结果 | 信号 |
|---|---:|
| 结果值等价 | +1.00 |
| SQL 可执行但结果错误 | +0.20 |
| 提交 SQL 但不可执行 | +0.05 |
| 解析失败 | -0.30 |
| 协议无效 | -0.20 |
| 超出步数预算 | -0.10 |
| 非只读 SQL | -1.00 |
| 第 6 步之后继续调用 | 每步 -0.02 |

此外，`final_sql` 应等于最后一次成功执行的 SQL。这样可以避免模型执行了
正确查询，却在 final 阶段提交未经验证的另一条 SQL。

## 训练配置

| 配置 | 值 |
|---|---:|
| 优化算法 | GRPO |
| group size | 4 |
| learning rate | 5e-7 |
| KL coefficient | 0.002 |
| KL type | low_var_kl |
| actor / rollout GPU | 2 / 2 |
| tensor parallel | 2 |
| optimizer CPU offload | enabled |

早期 3 卡配置在 Megatron 的 logprob / entropy 路径出现显存不足。最终用
4 卡将 actor 与 rollout 隔离，并结合 tensor parallel、activation
recompute、dynamic batching 和 optimizer CPU offload 完成训练。

## 验证结果

| Rollout | Avg reward | Strict | Equivalent | Executable | Protocol |
|---:|---:|---:|---:|---:|---:|
| 49 | 0.6275 | 50.8% | 60.0% | 90.0% | 99.2% |
| 99 | 0.7196 | 62.5% | 70.0% | 95.0% | 100.0% |
| 199 | 0.7596 | 65.8% | 71.7% | 95.0% | 100.0% |
| 249 | 0.7846 | 66.7% | 75.0% | 95.8% | 100.0% |
| **349** | **0.8163** | **73.3%** | **78.3%** | **95.0%** | **100.0%** |
| 499 | 0.7858 | 70.8% | 75.8% | 92.5% | 100.0% |

最佳点是 rollout 349。rollout 499 仍明显优于早期点，但已有小幅回落，
因此正式模型选择应依据固定 validation 的最佳 checkpoint，而不是默认取
最后一个 checkpoint。

SFT full-dev 与 RL validation 不是同一任务集合，不能把两组数字直接当成
严格的阶段增益。可靠结论来自 RL validation 内部的同集曲线。
