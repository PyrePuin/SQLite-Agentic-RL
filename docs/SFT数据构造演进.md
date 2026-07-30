# SFT 数据构造演进：从失败的 V1 到 SQLite V2

## 1. 问题背景

项目目标不是只让模型生成一条 SQL，而是让 3B 模型在真实 SQLite 环境中
完成多轮工具调用：

```text
理解问题 -> 探索 schema -> 执行 SQL -> 接收环境反馈 -> 修复或结束
```

这要求训练数据同时覆盖 SQL 能力、动作选择、工具协议、错误恢复和及时
finalize。V1 的核心问题，是试图用一批混合数据一次性解决所有能力，却没有
先验证每一层是否真正学会。

## 2. V1 为什么判定为失败

V1 曾尝试 XML 包装协议：

```xml
<tool_call>{"name":"execute_sql","arguments":{"sql":"SELECT ..."}}</tool_call>
```

模型更容易学习内部 JSON，却经常省略 XML 标签。兼容解析器能够挽救部分
SQL 和工具行为，但严格协议通过率长期接近 0。对 Agent 项目而言，“兼容
解析后偶尔能跑”不等于 runtime 可用，因此整个 V1 SFT 按工程验收标准判定
失败。

随后直接在这份不稳定策略上进行了数次 RL 探索。结果是奖励同时受到格式
失败、无法结束、SQL 错误和环境错误影响，训练难以判断应该优化哪一层。
这说明 RL 不能替代冷启动：如果 action space 和基本协议尚未稳定，在线
采样只会放大噪声。

## 3. 失败路径带来的具体认识

### 3.1 没有协议专项训练

早期数据把协议 token 当作普通文本的一小部分。SQL、schema 和 observation
远长于外层标签，模型即使忽略协议也能持续降低 loss。后来引入短小的
protocol anchor，专门训练：

- question -> canonical tool call；
- observation -> 下一次 canonical action；
- 成功执行 -> canonical final。

### 3.2 XML 与模型先验不匹配

Coder/Instruct 模型已有较强 JSON / function-call 先验。额外要求 XML 外壳
增加了一个与任务正确性无关、但会导致整条轨迹无法解析的失败面。V2 因此
改为每轮只输出一个 JSON 对象：

```json
{"type":"tool_call","name":"execute_sql","arguments":{"sql":"SELECT ..."}}
```

```json
{"type":"final","final_sql":"SELECT ...","answer":"..."}
```

正式 runtime 只接受 `json_v2`；XML 解析器只留在历史迁移模块中。

### 3.3 机械 repair 数据并不等于错误恢复

早期 repair 主要通过人工替换表名、列名或拼接固定错误模板得到。它能教会
模型“错误后再输出一次”，但容易产生三类副作用：

- 错误过于单一，模型记住模板而不是诊断 observation；
- 修复路径不自然，与真实模型会犯的错误分布不同；
- 固定工具链让模型机械调用工具，而不是根据环境状态选择动作。

因此正式数据只把机械 repair 当作早期探索，后续重点转为真实 student /
teacher 执行失败产生的 transition。`repair_real` 保留“错误 SQL、SQLite
反馈、修正 SQL”之间的因果关系。

### 3.4 只看训练 loss 无法选择 Agent checkpoint

训练 loss 下降不代表协议可解析、SQL 可执行或结果正确。V2 将评测拆成：

- canonical protocol valid；
- submitted / finalization；
- SQL executable；
- strict result；
- equivalent output；
- parse failed / budget exceeded。

checkpoint 必须通过真实 rollout 选择，而不是默认使用最后一步。

## 4. SQLite V2 的数据构造

V2 首先把历史 5,000 条混合数据迁移为纯 JSON，去除 14 条长度异常样本，
再加入 500 条 protocol anchor，形成 5,486 条 V2 JSON base。这个阶段没有
重新调用 Teacher，而是对已有知识进行协议重构。

之后运行真实 Teacher Agent：

```text
hard task pool
-> Teacher 在 SQLite runtime 中自主调用工具
-> SQLite verifier 执行 final_sql
-> 对 strict-fail 样本进行审计
-> 保留 verifier-successful trace
```

620 条去重 Teacher rollout 最终筛出 331 条成功轨迹。它们保留了真实的动作
选择、值探测、SQL 执行与结束过程，而不是机械展开
`list_tables -> get_schema -> execute_sql(gold)`。

从知识来源上看，这也是一次小规模行为蒸馏：Teacher 提供可执行的 Agent
轨迹，3B student 通过 SFT 学习其决策过程；SQLite verifier 决定轨迹是否
可用，避免把 Teacher 的错误直接蒸馏给 student。

## 5. 最终 5,817 条数据

| 类型 | 数量 | 主要作用 |
|---|---:|---|
| teacher_agent | 2,045 | 已有 Teacher Agent 行为 |
| sql_core | 1,100 | 保持基础 SQL 能力 |
| agent_trace | 876 | 多轮工具调用 |
| schema_only | 714 | schema 理解和动作选择 |
| protocol_anchor | 500 | 固定 JSON 协议 |
| repair_real | 251 | 真实执行错误后的修复 |
| teacher_agent_real_v3 | 331 | 新采集且通过 verifier 的真实轨迹 |

最终文件为：

```text
data/sft/v3_real_json/sft_v3_real_json_5817.jsonl
```

5,817 条对通用语言模型预训练而言很小，但对单一 SQLite Agent 行为的 LoRA
冷启动并不小。解释数据规模时，重点不是“行数足够大”，而是：

- 数据目标窄且协议统一；
- 每条多轮轨迹包含多个监督位置；
- SQL core、协议、repair 和真实轨迹各自承担明确职责；
- 数据经过执行验证，信息密度高于无筛选扩量；
- 最终效果由独立 rollout 评测和后续 RL 验证，而不是由数据量自证。

## 6. 最终结论

这次演进不是简单把 XML 替换成 JSON，而是重新确定训练顺序：

```text
先稳定 SQL 与协议
-> 再用真实轨迹学习工具行为
-> 用 verifier 清洗 Teacher 与 repair
-> 用 Agent 评测选择 SFT checkpoint
-> 最后进入在线 RL
```

V1 的价值是暴露边界；SQLite V2 才是满足正式训练和 RL 冷启动要求的工程
基线。
