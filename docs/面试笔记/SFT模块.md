# SFT 模块面试学习笔记

SFT 在本项目中的任务不是把 3B 模型直接训练到最终最优，而是建立一个可供 RL 在线采样的稳定初始策略：它要会生成 SQL，也要会遵守动作协议、读取环境反馈、在错误后继续修复，并在成功执行后正确结束。

## 1. SFT 在全链路中的位置

```text
可执行任务池
-> SQL core / protocol / Agent trace / repair / Teacher 数据
-> LoRA SFT
-> 真实 Agent rollout 评测
-> 选择 checkpoint-600
-> 合并 LoRA
-> Slime GRPO
```

如果协议和基本工具行为都不稳定就直接做 RL，奖励会同时混入格式错误、解析失败、SQL 错误和无法结束，在线采样效率很低。SFT 的本质是缩小 RL 的有效 action space，让大多数轨迹至少可解析、可执行、可结束。

## 2. 训练数据学的不是同一种能力

正式文件为 `data/sft/v3_real_json/sft_v3_real_json_5817.jsonl`，共 5,817 条：

| 数据类型 | 数量 | 对应能力 |
|---|---:|---|
| `sql_core` | 1,100 | 给定 schema 直接生成可执行 SQL |
| `schema_only` | 714 | 识别相关表和字段，选择 schema 工具 |
| `protocol_anchor` | 500 | 输出唯一 canonical JSON 对象 |
| `agent_trace` | 876 | 多轮 action—observation—action |
| `repair_real` | 251 | 历史 Repair 来源；其中 142 条明确含失败反馈 |
| `teacher_agent` | 2,045 | Teacher 工具行为蒸馏 |
| `teacher_agent_real_v3` | 331 | 新采集且经 verifier 验证的真实轨迹 |

最终文件中有 5,506 个 final target、16,182 个 tool-call target，共 21,688 个 assistant 监督位置。因此“5,817 行”不能直接等同于 5,817 次单轮监督。

## 3. 训练样本长什么样

Agent 样本采用 messages：

```text
system: JSON V2 规则与四个工具
user: 自然语言问题
assistant: tool_call JSON
user: tool_result JSON
assistant: 下一次 tool_call / final JSON
```

例如：

```json
{"type":"tool_call","name":"execute_sql","arguments":{"sql":"SELECT ..."}}
```

```json
{"type":"tool_result","result":{"ok":false,"error":"no such column: ..."}}
```

```json
{"type":"tool_call","name":"get_schema","arguments":{"table_names":["orders"]}}
```

这类 Repair 主要监督的是条件行为：看到具体错误 observation 后如何改变下一步动作，而不是训练一个独立的“结果判错器”。

这里要区分两种 `ok=false`：

- SQL 语法错误、缺表、缺列等执行错误由 SQLite 直接返回，模型能从真实 runtime observation 中看到；
- `wrong_result` 表示 SQL 可以执行但结果与 Gold Result 不等价，它必须由离线 verifier 对比后注入，模型本身没有 Gold，无法独立确认结果错误。

因此，`wrong_result` 对模型来说首先是一个外部反馈信号。SFT 通过包含“反馈 → 修改 SQL”转移的样本，让模型学习这个信号意味着应该继续检查 Schema、结果列或 SQL 逻辑，而不是马上 `final`。但如果推理时没有 Gold verifier、用户反馈或其他外部检查，模型仍可能提交一条可执行但语义错误的 SQL。

当前正式数据中的 `sql_core` 将 Schema 与问题放进 User context，Assistant 输出 JSON `final`，不经过工具循环。它的作用是避免多轮协议训练稀释基础 SQL 能力；判断已训练数据形态时应以正式 JSONL 为准。

## 4. 从失败的协议训练得到什么

V1 使用 XML envelope 包裹 JSON。模型经常生成内部 JSON，却漏掉 XML 标签；兼容 parser 能救回一些内容，但严格协议通过率仍不能满足 runtime 要求。随后在不稳定策略上进行的多次 RL 也失败，因为模型连合法动作空间都没有站稳。

V2 做了三件事：

1. 改为更符合 Coder/Instruct 先验的纯 JSON function-call 协议；
2. 增加 500 条短小 protocol anchor，让协议 token 不再被长 schema/SQL 文本淹没；
3. 把协议、可执行性、结束率和结果正确率拆成独立评测指标。

因此 V1 到 V2 不是单纯替换标签，而是重新安排能力学习顺序：先稳定表示和基本动作，再学习复杂轨迹，最后进入 RL。

## 5. Teacher 轨迹是一种行为蒸馏

项目先从 train split 构造 1,000 条困难英文候选，再让 DeepSeek V4 Pro 在真实 runtime 中自行决定何时查 schema、预览值、执行 SQL、修复或结束。620 条去重 rollout 中只有 331 条通过 verifier，并入正式 SFT。

这属于带环境验证的行为蒸馏：

- Teacher 生成的不只是答案，而是中间工具决策；
- SQLite 环境提供真实 observation；
- verifier 只保留结果正确的正向轨迹；
- Student 通过 teacher forcing 学习这些状态—动作映射。

真实 Teacher 轨迹平均 4.704 次工具调用，最少 3、最多 9；其中包含 590 次 `execute_sql`，说明一些成功轨迹经历了多次尝试，而不是固定把 Gold SQL 展开成三步模板。

## 6. LoRA 训练配置

正式训练模型为 `Qwen2.5-Coder-3B-Instruct`：

| 参数 | 值 |
|---|---:|
| 训练方式 | PEFT LoRA |
| LoRA rank | 32 |
| LoRA alpha | 64 |
| LoRA dropout | 0.05 |
| precision | bf16 |
| max sequence length | 2,048 |
| micro batch size | 1 |
| gradient accumulation | 16 |
| effective batch size | 16 |
| epochs | 2 |
| learning rate | `1e-4` |
| scheduler | cosine |
| warmup ratio | 0.03 |
| gradient checkpointing | enabled |
| `use_cache` | false |

LoRA rank 32 / alpha 64 提供足够容量学习协议与工具行为，同时避免全量微调的显存和 checkpoint 成本。`bf16 + gradient checkpointing + micro batch 1` 主要服务于有限显存；梯度累积把有效 batch 提升到 16。

最大长度 2,048 是成本与轨迹完整性的折中。正式训练前使用 `inspect_sft_token_lengths.py` 检查长度分布，构造阶段已经去掉 14 条异常长样本，避免大量截断破坏 action—observation 对齐。

## 7. 为什么不能只看 loss

Teacher-forcing loss 只衡量“给定正确历史时能否预测下一个 token”。真实 Agent 还会遇到自身生成造成的状态分布偏移：一个错误 action 会带来不同 observation，并影响所有后续轮次。

因此 checkpoint 通过真实 rollout 评测，主要指标为：

| 指标 | 说明 |
|---|---|
| `canonical_protocol_valid` | 每轮是否满足唯一 JSON schema |
| `submitted/finalization` | 是否在预算内输出 final |
| `pred_executable` | 最终 SQL 是否可执行 |
| `strict_pass` | 列名与完整结果均一致 |
| `equivalent_output` | 完整结果值等价，允许列别名差异 |
| `parse_failed` | 是否无法解析 action/final |
| `budget_exceeded` | 是否用完步数仍未结束 |

三档 dev 评测控制成本：mini 110、fast 120、full 300。现有正式记录中，最终选择的 `checkpoint-600` 在 full-dev 上得到：

| 指标 | 结果 |
|---|---:|
| strict 或 equivalent | 66.33% |
| strict | 44.00% |
| canonical protocol | 90.33% |
| finalization | 94.33% |
| executable | 94.33% |
| parse failed | 2.67% |
| budget exceeded | 3.00% |

这里 strict 与 equivalent 差距较大，部分原因是列别名不同但值完全一致。项目把 equivalent 作为语义正确主口径，同时保留 strict 用于观察输出规范性。结构化摘要见 [`results/sft/checkpoint600.summary.json`](../../results/sft/checkpoint600.summary.json)。该摘要由现有正式记录转录，仓库没有逐任务原始 rollout；同时，历史 SFT 数据来源使这组数字不能单独证明严格未见 schema 泛化。

## 8. SFT 后模型还错在哪里

SFT 后协议和可执行性已经较高，主要错误从“根本跑不起来”转为“SQL 能执行但结果错误”：

- join 路径或聚合粒度错误；
- literal grounding 错误；
- `GROUP BY`、`HAVING`、嵌套查询或集合操作语义错误；
- 执行了正确 SQL，却没有按协议提交同一条 `final_sql`；
- 少量解析失败或超出工具预算。

这正是进入 RL 的条件：奖励能够区分正确、可执行但错误、不可执行、协议失败，而不再被大量格式噪声淹没。

## 9. 如何复现训练与评测

```bash
export PYTHONPATH="$PWD/sqlite_agent:${PYTHONPATH:-}"
BASE_MODEL=/path/to/Qwen2.5-Coder-3B-Instruct

python sqlite_agent/scripts/sft/run_formal_sft_eval.py \
  --model "$BASE_MODEL" \
  --train-data data/sft/v3_real_json/sft_v3_real_json_5817.jsonl \
  --mini-dev data/eval/mini_dev.jsonl \
  --fast-dev data/eval/fast_dev.jsonl \
  --full-dev data/eval/full_dev.jsonl \
  --output-dir checkpoints/qwen25_coder3b_sqlite_sft \
  --epochs 2 \
  --train-samples 5817 \
  --effective-batch-size 16 \
  --eval-every-steps 100 \
  --max-length 2048 \
  --learning-rate 1e-4 \
  --bf16
```

单独评测必须明确基座、adapter 和任务集，不能只拿 adapter 目录直接生成。

## 10. 面试表达

### 一分钟版本

> SFT 的目标是给 Agentic RL 提供稳定冷启动，而不是在监督阶段解决所有 SQL 问题。我们用 Qwen2.5-Coder-3B-Instruct 做 LoRA，正式数据 5,817 条，但包含 21,688 个 assistant 监督位置，分别覆盖 SQL core、协议、schema 动作、多轮轨迹、真实 repair 和 verifier 成功的 Teacher 轨迹。训练用 rank 32、alpha 64、bf16、长度 2048、有效 batch 16、2 epochs、学习率 1e-4。checkpoint 不按 loss 选，而是按真实 Agent 评测选择；现有记录中 checkpoint-600 在 300 条 full-dev 上达到 94.3% 可执行率和 66.3% strict-or-equivalent。这个结果用于说明固定流程下的能力，不夸大为严格未见 schema 泛化。

### 常见追问

**为什么既有 SQL core 又有 Agent trace？**

前者保住纯 SQL 能力，后者学习动作选择和环境反馈。如果只训轨迹，协议与 observation 可能稀释 SQL token；只训 SQL 又不会调用工具。

**为什么不用最后一个 checkpoint？**

loss 和 Agent 成功率不严格单调，后期还可能过拟合协议模板或特定任务。固定 dev rollout 的最佳点才是模型选择依据。

**这是不是蒸馏？**

331 条真实 Teacher 轨迹属于行为蒸馏，但完整 SFT 不只是蒸馏，还包含确定性 SQL core、协议锚点、已有轨迹和真实 repair。

**模型真的“理解” `wrong_result` 吗？**

它没有 Gold Result，不能独立证明结果错误。`wrong_result` 是外部 verifier 注入的反馈；Repair SFT 主要训练模型在收到该反馈后如何修改 SQL，而不是训练模型自己充当结果判定器。
