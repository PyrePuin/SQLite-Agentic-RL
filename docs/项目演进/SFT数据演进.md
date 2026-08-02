# SFT 数据演进：从 V1 自动轨迹到 5,817 条 JSON Agent 数据

## 1. 这份文档记录什么

这个项目不是从一开始就拥有现在的 7 类 SFT 数据。数据设计经历了三次主要转变：

1. 从单轮 SQL 监督转向自动拼接的工具轨迹；
2. 从提前知道 Gold SQL 的 Oracle 轨迹转向真实环境 Teacher rollout；
3. 从 XML 包装协议转向单 JSON 对象，并用 Repair 和 Protocol Anchor 补充恢复与接口监督。

本文是一份公开技术复盘，重点解释每个阶段为什么出现、暴露了什么问题，以及下一阶段怎样回应这些问题。数字采用三种证据口径：

- **脚本和 manifest 可验证事实**：可以从 V1/V2 保留的构造代码与产物直接复核；
- **当前正式数据审计**：直接统计 `sft_v3_real_json_5817.jsonl` 的消息结构；
- **历史实验记录**：来自 V1 的实验文档，用于说明当时的判断，不把它升级成新的严格结论。

最终状态和 7 类完整 `messages` 示例见[《SFT 训练与数据构造》](../技术设计/SFT训练与数据构造.md)。

## 2. 时间线总览

| 阶段 | 当时的目标 | 暴露的问题 | 后续调整 |
|---|---|---|---|
| 自动 Gold/Oracle 轨迹 | 低成本建立 SQL 和工具格式 | 路径过于理想，没有真实决策和失败恢复 | 引入真实 Teacher |
| 扩大到 1,000/5,000 条 | 提高 Schema 与 SQL 覆盖 | 格式改善后，瓶颈转为 SQL 语义和恢复 | 分析失败分布，不再只堆成功模板 |
| 真实 Teacher | 蒸馏 observation 驱动的动作 | Teacher 也会失败；最终成功不代表中间轨迹完美 | 执行 verifier 门控，并回流失败 |
| Recovery / Repair | 教模型看到失败后修改 SQL | 纯 Recovery 造成分布偏移；真实失败多为 wrong-result | 少量混入真实 Repair |
| XML V1 | 用标签区分工具调用和 final | 小模型常输出正确内部 JSON，却省略 XML 外壳 | 放弃 XML checkpoint，统一 JSON |
| JSON V2 | 对齐基础模型 function-call 先验 | 长轨迹里协议 token 权重仍弱 | 加入短 Protocol Anchor |
| V3-real Teacher | 补充困难多表真实决策 | 成功率受复杂任务限制 | 只合入 verifier 成功的 331 条 |
| 最终 5,817 条 | 分层承担 SQL、决策、恢复和协议职责 | `repair_real` 历史标签不够精确 | 文档和后续构造以消息内容审计为准 |

## 3. 第一阶段：用 Gold SQL 自动构造成功轨迹

### 3.1 当时为什么这样做

真实 Teacher rollout 需要反复调用外部模型和 SQLite 环境，早期更需要先验证：

- LoRA 训练是否能跑通；
- 模型是否能输出结构化动作；
- observation 是否能重新进入上下文；
- 一个小模型能否学会何时提交 `final`。

Spider/CSpider 已经提供问题、Gold SQL 和数据库，因此最便宜稳定的冷启动方法，是直接用已知答案拼出成功轨迹。

### 3.2 三种自动数据怎样得到

#### `sql_core`

```text
Gold SQL
→ 根据 SQL 推断相关表
→ 读取 Schema 并与问题拼接
→ Gold SQL + Gold Result 组成 final
```

它保留短路径 SQL 监督，但不教授工具使用。

#### `schema_only`

```text
问题
→ get_schema(Gold SQL 涉及的表)
→ execute_sql(Gold SQL)
→ final
```

它教授最短工具闭环，但相关表由构造器从 Gold SQL 推断，并不是模型自己探索出来的。

#### `agent_trace`

```text
问题
→ list_tables
→ get_schema(Gold SQL 涉及的表)
→ optional preview_rows
→ execute_sql(Gold SQL)
→ final
```

`preview_rows` 由字面量、日期、城市、国家和名称等启发式规则触发。轨迹更像 Agent，但第一条执行 SQL 通常仍然是 Gold SQL。

V1 保留的自动数据 manifest 显示，一版 5,000 条自动包包含：

| 类型 | 数量 |
|---|---:|
| `sql_core` | 2,978 |
| `schema_only` | 990 |
| `agent_trace` | 1,032 |
| **合计** | **5,000** |

### 3.3 实际发生了什么

自动数据非常适合学习格式、工具名称和成功流程，但它有明显的 Oracle 偏差：构造程序提前知道正确 SQL，因此也提前知道相关表、正确执行动作和何时结束。

模型看到的是：

```text
理想观察
→ 正确 SQL
→ 成功结果
→ final
```

它很少看到：

```text
选错表
→ SQL 失败或结果不对
→ 重新查看 Schema
→ 修改 SQL
```

因此，自动轨迹能建立行为外形，却不能完整教授不确定状态下的决策。

## 4. 第二阶段：从 smoke 扩大到 1,000 和 5,000 条

### 4.1 当时为什么扩量

早期 32 条左右的 smoke 数据主要验证训练和 runtime 接口。模型能够产生合法动作后，下一步自然是增加任务和数据库覆盖，让模型见到更多表名、字段、JOIN 与聚合结构。

### 4.2 历史实验记录显示了什么

V1 文档记录：

- 1,000 条阶段已经能在训练分布上较稳定地完成任务，但验证表现明显更低；
- 扩展到更多数据库和约 5,000 条后，一组 60 题阶段性验证达到 `36/60 = 60%`；
- 继续训练并没有持续带来同等幅度的验证提升。

这些数字用于还原当时的决策背景，不作为当前 checkpoint 的重新评测结果。

错误分析逐渐从“能否输出协议”转向：

- 未见 Schema 上的表/字段语义映射；
- 多表 JOIN 路径；
- 字面量与真实数据库值的对应；
- SQL 可以执行但返回结果错误；
- 失败后重复相同动作。

### 4.3 后来怎样调整

这一阶段说明：普通成功轨迹继续扩量仍有价值，但边际收益会下降。数据需要开始覆盖“为什么采取下一步动作”和“错误后怎样改变动作”，而不只是增加理想成功路径。

## 5. 第三阶段：引入真实环境 Teacher

### 5.1 自动轨迹缺少什么

自动构造器知道 Gold SQL，而真正的 Agent 并不知道。为了得到更自然的行为，项目使用 DeepSeek V4 Pro 作为 Teacher，让它在真实 SQLite 环境中逐步行动：

```text
Teacher 读取问题和历史 messages
→ 生成一个工具调用
→ SQLite 执行工具
→ tool_result 追加到 messages
→ Teacher 继续决定下一步
→ Teacher 输出 final
→ verifier 执行 final_sql 并与 Gold Result 比较
```

这是一种 trajectory / behavior distillation：Student 学习的是 Teacher 的状态—动作序列，不是 Teacher 的 logits。

### 5.2 第一批 Teacher 的数量变化

V1 manifest 和构造记录可以对齐出以下链路：

```text
3,760 条困难候选
→ 2,167 条执行结果验证成功
→ 2,053 条通过消息与协议清洗
→ JSON V2 长度过滤后保留 2,045 条
```

Teacher 数据提供了自动轨迹很难表达的变化：

- 不同题目的工具顺序不同；
- 是否预览数据由真实上下文决定；
- Teacher 会根据 observation 选择下一步；
- SQL 和轨迹长度更接近真实 rollout 分布。

### 5.3 Teacher 为什么仍需要 verifier

Teacher 输出 `final` 只代表它认为自己完成了任务。项目仍要：

1. 执行 `final_sql`；
2. 检查 SQL 是否可执行；
3. 比较预测列、行值、顺序和重复项约束；
4. 只有结果满足任务口径才标记成功。

所以 verifier 在 Teacher 链路中不是奖励装饰，而是数据质量门控。

## 6. 第四阶段：从 Recovery-SFT 到真实 Repair

### 6.1 为什么先尝试 Recovery

早期 RL 实验暴露出模型几乎不会在失败后恢复。奖励可以降低一步盲提交，却没有自动创造“阅读错误—修改 SQL—重新执行”的行为先验。

项目曾自动构造约 3,000 条 Recovery 轨迹，例如：

```text
人为破坏 SQL
→ no such column
→ get_schema / preview_rows
→ Gold SQL
→ 成功
```

V1 历史记录显示，从通用 SFT checkpoint 继续进行纯 Recovery-SFT 后，一组 48 题验证从 `23/48` 下降到 `18/48`，随后为 `16/48`。

### 6.2 为什么纯 Recovery 会回退

可能原因不是“修复行为没有价值”，而是数据分布失衡：

- 所有题都先失败，模型容易形成先犯错再修的偏置；
- 机械造错与真实模型错误分布不同；
- 专项 Repair 占比过高，覆盖普通成功轨迹；
- 继续训练可能遗忘直接正确解题的能力。

策略因此改为：成功轨迹仍是主体，只混入少量通过验证的真实 Repair。

### 6.3 真实失败怎样回流

V1 的 `build_real_repair_requests.py` 将失败 Teacher rollout 分为：

- `parse_failed`；
- `no_such_column` / `no_such_table`；
- `ambiguous_column` / `syntax_error`；
- `sql_execution_failed`；
- `wrong_result`；
- `unfinished` / `expert_failed`。

随后构造 Repair seed：

```text
原问题
+ 必要的 Schema context
+ 首次失败 SQL
+ verifier 结构化失败反馈
→ seed_messages
→ Teacher 从该上下文继续
→ 最终 verifier 成功才保留
```

真实失败审计显示，主要难点不是 SQLite 语法错误，而是 SQL 能执行但结果不匹配。对于这种 `wrong_result`：

- SQLite 只能返回一次成功执行结果；
- verifier 需要将预测结果与 Gold Result 比较；
- 数据构造器再把 `wrong_result`、行列差异和修正指令写回 `tool_result`。

这也是为什么普通线上 runtime 无法凭空知道一个可执行结果是否语义正确。

### 6.4 V1 的 252 条 Repair 从哪里来

V1 最终混合数据有 252 条 `repair_real`：

```text
247 条标记为 Repair 的成功 Teacher rollout
+ 5 条从成功 Teacher 轨迹内部抽取的执行错误修复
= 252 条
```

其中 5 条由 `extract_execution_repairs.py` 抽取：脚本在成功轨迹中寻找 `syntax error`、`no such column` 等失败 observation，保留失败动作与后续成功 tail。

### 6.5 当前审计发现的标签问题

V1 的混合脚本将成功 Repair rollout 统一标记为 `repair_real`，验收条件主要是：

- rollout 的 `success=true`；
- messages 能被清洗；
- 恰好有一个 `final`。

它没有再次要求 messages 中必须出现失败 observation。采集参数中的 `mode=repair` 也不会自动证明实际 transcript 从失败上下文开始。因此，来源标签和消息内容出现了偏差。

对 V1 的 252 条直接审计：

| 实际消息形态 | 数量 |
|---|---:|
| 明确失败后继续动作 | 142 |
| 无显式失败，但多次执行 SQL | 33 |
| 无失败且只执行一次 SQL | 77 |
| **合计** | **252** |

JSON V2 转换时，长度过滤删除了 1 条普通成功轨迹，当前正式 251 条变为：

| 实际消息形态 | 数量 |
|---|---:|
| 明确失败后继续动作 | 142 |
| 无显式失败，但多次执行 SQL | 33 |
| 无失败且只执行一次 SQL | 76 |
| **合计** | **251** |

因此，当前 `repair_real` 应理解为**历史 Repair 来源标签**。严格意义的 repair loop 必须从消息内容确认存在“失败 observation → 后续 Assistant 动作”，不能只看 variant 名。

## 7. 第五阶段：XML V1 为什么被放弃

### 7.1 V1 协议

V1 使用 XML 外壳包装 JSON：

```xml
<tool_call>{"name":"get_schema","arguments":{"table_names":["Movie"]}}</tool_call>
```

```xml
<final>{"final_sql":"SELECT title FROM Movie","answer":"Avatar"}</final>
```

### 7.2 实际问题

历史评测中，模型经常生成正确的内部 JSON，却省略外层 XML：

```json
{"name":"get_schema","arguments":{"table_names":["Movie"]}}
```

兼容 parser 可以挽救部分任务行为，但严格 XML 协议有效率长期不理想。可能原因包括：

- Qwen Coder 的先验更接近 JSON/function call；
- XML 标签只占很少 token，容易被长 Schema 和 SQL 的 loss 淹没；
- 长轨迹截断会进一步削弱末尾 `final` 和闭合标签监督；
- XML 外壳没有增加数据库任务本身的表达能力。

### 7.3 后来怎样调整

项目没有继续给 XML 增加 parser 补丁，而是放弃旧 XML checkpoint，从基础模型重新训练单 JSON 对象协议。

## 8. 第六阶段：JSON V2 与 Protocol Anchor

### 8.1 复用 V1 中昂贵的轨迹

V1 的接口失败，不代表 Teacher 决策全部无效。`build_sft_v2_json.py` 对 5,000 条历史混合轨迹执行：

```text
替换 system prompt
→ XML Assistant 动作转 canonical JSON
→ Tool Result 转 canonical JSON
→ 检查合法工具与唯一 final
→ 过滤长度异常样本
```

数量变化为：

```text
5,000 条 V1 mixed
→ 5,000 条完成协议转换
→ 删除 14 条长度异常
→ 4,986 条 clean JSON 轨迹
```

这 4,986 条的 variant 为：

| 类型 | 数量 |
|---|---:|
| `sql_core` | 1,100 |
| `schema_only` | 714 |
| `agent_trace` | 876 |
| `teacher_agent` | 2,045 |
| `repair_real` | 251 |
| **合计** | **4,986** |

### 8.2 为什么还需要 Protocol Anchor

即便已经转为 JSON，完整轨迹仍含大量 Schema、SQL 和 observation token。关键协议边界只占很小比例：

- 第一次工具调用；
- 第一次 `execute_sql`；
- 成功 observation 后输出 `final`。

构造脚本从 clean 轨迹中截取这三类短片段，生成 600 条候选，固定随机种子选择 500 条：

| Anchor | 数量 |
|---|---:|
| `first_tool` | 158 |
| `execute_sql` | 155 |
| `final` | 187 |
| **合计** | **500** |

于是：

```text
4,986 clean
+ 500 protocol_anchor
= 5,486 条 V2 基础数据
```

Anchor 不增加新的 SQL 答案，作用是提高协议 token 和终止边界在训练中的相对权重。

## 9. 第七阶段：新增 331 条困难 Teacher

JSON V2 还补采了一批困难英文、多表任务。Teacher 仍然在真实 SQLite runtime 中自主调用工具，转换脚本要求：

- 原 rollout 的 `success=true`；
- messages 合法；
- 至少一个工具调用；
- 恰好一个 `final`；
- 使用冻结的 V2 system prompt。

数量变化为：

```text
620 条去重 rollout
→ verifier 与协议审核
→ 331 条 teacher_agent_real_v3
```

这批数据重点补充 JOIN、嵌套查询、集合运算和复杂多表行为，并与 5,486 条基础数据合并：

```text
5,486
+ 331
= 5,817
```

## 10. 最终 5,817 条怎样分工

| 类型 | 数量 | 来源 | 主要职责 |
|---|---:|---|---|
| `sql_core` | 1,100 | Gold 自动构造 | 短路径 SQL 语义 |
| `schema_only` | 714 | Gold Oracle 轨迹 | 最短 Schema/执行闭环 |
| `agent_trace` | 876 | Gold Oracle 完整轨迹 | 标准多轮工具流程 |
| `teacher_agent` | 2,045 | 历史真实 Teacher | observation 驱动的决策 |
| `repair_real` | 251 | 历史 Repair 来源 | 部分严格修复、部分迭代或普通成功轨迹 |
| `protocol_anchor` | 500 | 已有轨迹短切片 | JSON 接口和终止边界 |
| `teacher_agent_real_v3` | 331 | 新困难 Teacher | 高难度多表决策 |
| **合计** | **5,817** | — | Agent SFT 冷启动 |

可以把它理解成四层：

```text
SQL 基础
sql_core
    ↓
Oracle 工具基础
schema_only + agent_trace
    ↓
真实环境策略
teacher_agent + teacher_agent_real_v3
    ↓
恢复与接口稳定
repair_real + protocol_anchor
```

## 11. 这段演进留下的经验

### 11.1 自动轨迹适合冷启动，不等于真实策略

Gold 数据可以稳定地教 SQL、Schema 和工具格式，但模型没有经历不确定性。评估自动轨迹时，应明确它是 Oracle demonstration。

### 11.2 Verifier 有两个不同职责

- 采集结束时：判断整条 Teacher rollout 是否能进入正向 SFT；
- 构造 Repair 时：把某次失败转换为下一轮可读取的结构化反馈。

这两个职责都依赖真实执行结果，但不能混为一谈。

### 11.3 Repair 不能只看标签和数量

只有 `variant=repair_real` 不足以证明样本包含恢复行为。后续构造应直接验证：

- 是否存在明确失败 observation；
- 失败后是否还有 Assistant 动作；
- SQL 是否发生实质变化；
- 最终是否通过 verifier。

### 11.4 专项数据不能覆盖主分布

纯 Recovery-SFT 的回退说明，修复数据应该作为成功轨迹的少量补充，并单独评测恢复率，而不是让每道题都先失败。

### 11.5 协议应尽量对齐基础模型先验

当 JSON 已经能完整表达工具调用时，额外 XML 外壳只会增加学习和解析负担。Protocol Anchor 则是一种更直接的监督加权方式。

### 11.6 数据演进必须保留 lineage

最终文件应记录 source、构造脚本、协议版本、Teacher、verifier、split 和过滤原因。否则一个看似清晰的 variant 名，很容易随着多轮合并失去精确语义。

## 12. 继续阅读

- 7 类数据的完整精简 `messages` 和构造流程：[《SFT 训练与数据构造》](../技术设计/SFT训练与数据构造.md)
- 面试复习与 repair loop 三阶段解释：[《数据模块面试学习笔记》](../面试笔记/数据模块.md)
- 任务池、Gold 缓存和数据库划分：[《数据管线》](../技术设计/数据管线.md)
