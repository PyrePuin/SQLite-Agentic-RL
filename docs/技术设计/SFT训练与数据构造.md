# SFT 训练与数据构造

## 目标

SFT 的目标是给在线 RL 提供稳定初始策略：模型既要生成 SQL，也要遵守 JSON 动作协议、读取 SQLite observation、在执行错误后修复，并在成功后结束。

V1 使用 XML 外壳包装 JSON。兼容 parser 虽可救回部分输出，但标准协议通过率不稳定。V2 改用单一 JSON 对象，并加入短小的 protocol anchor，使协议 token 在长 schema 和 SQL 文本中获得足够监督权重。

## 正式数据

正式文件为 `data/sft/v3_real_json/sft_v3_real_json_5817.jsonl`：

| 类型 | 数量 | 目标 |
|---|---:|---|
| `sql_core` | 1,100 | 基础 SQL 生成 |
| `schema_only` | 714 | schema 理解与动作选择 |
| `protocol_anchor` | 500 | 标准 JSON 协议 |
| `agent_trace` | 876 | 多轮工具调用 |
| `repair_real` | 251 | 从真实 SQLite 错误恢复 |
| `teacher_agent` | 2,045 | 历史 Teacher 行为 |
| `teacher_agent_real_v3` | 331 | 新采集且通过 verifier 的轨迹 |
| **总计** | **5,817** | Agent 冷启动 |

其中共有 21,688 个 assistant 监督位置：5,506 个 final target 和 16,182 个 tool-call target。因此数据行数并不等同于单轮监督次数。

新增 Teacher 链路从 620 条去重 rollout 中筛出 331 条成功轨迹。Teacher 负责生成状态—动作轨迹，SQLite 返回真实 observation，verifier 作为质量门控；失败轨迹用于审计，不直接当作正向监督。

## LoRA 训练

| 参数 | 值 |
|---|---:|
| 基座 | Qwen2.5-Coder-3B-Instruct |
| LoRA rank / alpha / dropout | 32 / 64 / 0.05 |
| 精度 | bf16 |
| 最大长度 | 2,048 |
| micro batch / 梯度累积 | 1 / 16 |
| epochs | 2 |
| 学习率 | `1e-4` |
| scheduler | cosine |
| gradient checkpointing | 开启 |

正式编排器 `run_formal_sft_eval.py` 始终保留完整的 `max_steps`，只在评测边界暂停并从 Trainer checkpoint 恢复，从而保持 optimizer、scheduler、RNG 和 global step 连续。

## checkpoint 选择

训练 loss 只衡量 teacher forcing，不能代替真实 Agent rollout。checkpoint 同时比较协议、结束、可执行性、结果正确性、解析失败和超步数。现有记录选择 checkpoint-600；详细指标及证据等级见 [`results/sft/checkpoint600.summary.json`](../../results/sft/checkpoint600.summary.json)。

这些指标来自历史正式记录和 W&B run 元数据，并非仓库内重新执行产生的原始导出。它们证明该 checkpoint 在固定评测流程中的表现，不单独证明严格未见 schema 泛化。

## 复现入口

训练与评测命令见 [`sqlite_agent/scripts/sft/README.md`](../../sqlite_agent/scripts/sft/README.md)。评测 adapter 时必须同时指定基座模型、adapter、任务文件和协议，不能把 adapter 目录当作完整模型直接运行。
