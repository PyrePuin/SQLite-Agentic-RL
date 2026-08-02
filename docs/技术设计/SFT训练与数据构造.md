# SFT 训练与数据构造

## 1. 目标

SFT 的目标是给在线 RL 提供稳定的初始策略：模型既要生成 SQL，也要遵守 JSON 动作协议、读取 SQLite observation、在收到失败反馈后调整动作，并在成功后结束。

V1 使用 XML 外壳包装 JSON。兼容 parser 虽能救回部分输出，但严格 XML 协议不稳定。V2 改为每个 Assistant turn 只输出一个 JSON 对象，并加入短小的 `protocol_anchor`，让协议 token 在长 Schema 和 SQL 文本中获得更强监督。

## 2. 正式数据

正式文件为 [`data/sft/v3_real_json/sft_v3_real_json_5817.jsonl`](../../data/sft/v3_real_json/sft_v3_real_json_5817.jsonl)：

| 类型 | 数量 | 主要目标 |
|---|---:|---|
| `sql_core` | 1,100 | 基础 SQL 语义 |
| `schema_only` | 714 | Schema 阅读与工具闭环 |
| `protocol_anchor` | 500 | canonical JSON 协议 |
| `agent_trace` | 876 | 标准多轮工具流程 |
| `repair_real` | 251 | 失败反馈后的修正动作，以及历史 Repair 来源样本 |
| `teacher_agent` | 2,045 | 历史 Teacher 的真实环境行为 |
| `teacher_agent_real_v3` | 331 | 新采集且通过 verifier 的困难轨迹 |
| **总计** | **5,817** | Agent 冷启动 |

全部数据共有 21,688 个 Assistant 监督位置：5,506 个 `final` target 和 16,182 个 `tool_call` target。因此，数据行数不等同于单轮监督次数。

## 3. 怎样阅读 `messages`

每行 JSONL 的核心结构是：

```text
id, db_id, variant, messages
```

在 `messages` 中：

- `system`：定义工具和单 JSON 对象协议；
- 普通 `user`：提出任务；
- `assistant`：输出一个序列化后的 `tool_call` 或 `final` JSON 对象；
- 后续 `user`：用 `tool_result` JSON 携带环境 observation。

训练时，System、User 和 Tool Result 只作为条件上下文；只有 Assistant turn 计算 loss。模型学习的是：

\[
p_\theta(a_t \mid q, a_{<t}, o_{<t})
\]

下面的示例是“结构忠实的精简示意”：消息顺序、JSON 层级和动作语义与正式数据一致，但压缩了完整 system prompt、Schema 字段和行值。每节同时给出一个正式样本 ID，便于在 JSONL 中回查原始内容。

## 4. 七类数据详解

### 4.1 `sql_core`：直接 SQL 语义监督

#### 完整精简 `messages`

```json
[
  {
    "role": "system",
    "content": "你是 SQLite Agent。每个 Assistant turn 只输出一个 JSON 对象。"
  },
  {
    "role": "user",
    "content": "Database schema:\nMovie(title TEXT, year INTEGER, director TEXT)\n\nQuestion:\n列出 2000 年后由 James Cameron 执导的电影名。"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"final\",\"final_sql\":\"SELECT title FROM Movie WHERE year > 2000 AND director = 'James Cameron'\",\"answer\":\"Avatar\"}"
  }
]
```

#### 构造流程

```text
Task 的 Gold SQL
→ 从 Gold SQL 推断相关表
→ 读取相关 Schema 并与问题拼成 User context
→ Gold SQL 和 Gold Result 组成 JSON final
```

它不教授工具选择和错误恢复，作用是避免 SQL 监督被长轨迹稀释。需要注意：当前正式文件中的 `sql_core` Assistant 输出是 JSON `final`，不是裸 SQL。仓库中的独立新构造脚本可能生成不同形态，判断已训练数据时应以正式 JSONL 为准。

正式样本：`spider_001689__sql_core__json_v2`。

### 4.2 `schema_only`：最短工具闭环

#### 完整精简 `messages`

```json
[
  {
    "role": "system",
    "content": "你是 SQLite Agent。可调用 get_schema 和 execute_sql，每轮只输出一个 JSON 对象。"
  },
  {
    "role": "user",
    "content": "列出 2000 年后由 James Cameron 执导的电影名。"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"get_schema\",\"arguments\":{\"table_names\":[\"Movie\"]}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"tables\":{\"Movie\":{\"columns\":[{\"name\":\"title\",\"type\":\"TEXT\"},{\"name\":\"year\",\"type\":\"INTEGER\"},{\"name\":\"director\",\"type\":\"TEXT\"}]}}}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"execute_sql\",\"arguments\":{\"sql\":\"SELECT title FROM Movie WHERE year > 2000 AND director = 'James Cameron'\"}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"columns\":[\"title\"],\"rows\":[[\"Avatar\"]]}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"final\",\"final_sql\":\"SELECT title FROM Movie WHERE year > 2000 AND director = 'James Cameron'\",\"answer\":\"Avatar\"}"
  }
]
```

#### 构造流程

```text
Gold SQL
→ 根据 SQL 文本匹配相关表
→ get_schema(相关表)
→ execute_sql(Gold SQL)
→ 注入 Gold Result observation
→ final
```

相关表由构造程序提前根据 Gold SQL 推断，因此这是 Oracle 成功轨迹。它能教会最短工具闭环，但不能证明模型自己学会了选表。

正式样本：`spider_002446__schema_only__json_v2`。

### 4.3 `agent_trace`：自动构造的标准 Agent 流程

#### 完整精简 `messages`

```json
[
  {
    "role": "system",
    "content": "你是 SQLite Agent。可调用 list_tables、get_schema、preview_rows、execute_sql。"
  },
  {
    "role": "user",
    "content": "列出 2000 年后由 James Cameron 执导的电影名。"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"list_tables\",\"arguments\":{}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"tables\":[\"Movie\",\"Rating\",\"Reviewer\"]}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"get_schema\",\"arguments\":{\"table_names\":[\"Movie\"]}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"tables\":{\"Movie\":{\"columns\":[{\"name\":\"title\"},{\"name\":\"year\"},{\"name\":\"director\"}]}}}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"preview_rows\",\"arguments\":{\"table_name\":\"Movie\",\"limit\":3}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"columns\":[\"title\",\"year\",\"director\"],\"rows\":[[\"Avatar\",2009,\"James Cameron\"]]}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"execute_sql\",\"arguments\":{\"sql\":\"SELECT title FROM Movie WHERE year > 2000 AND director = 'James Cameron'\"}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"columns\":[\"title\"],\"rows\":[[\"Avatar\"]]}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"final\",\"final_sql\":\"SELECT title FROM Movie WHERE year > 2000 AND director = 'James Cameron'\",\"answer\":\"Avatar\"}"
  }
]
```

#### 构造流程

```text
Task
→ list_tables
→ get_schema(Gold SQL 涉及的表)
→ optional preview_rows
→ execute_sql(Gold SQL)
→ final
```

`preview_rows` 并非每条都有。构造脚本会在问题包含引号字符串、日期、城市、国家、名称等字面量线索时用启发式规则加入预览。整个过程仍提前知道 Gold SQL，第一条执行 SQL 通常就是正确 SQL。

正式样本：`spider_002442__agent_trace__json_v2`。

### 4.4 `teacher_agent`：历史真实环境 Teacher 轨迹

#### 完整精简 `messages`

```json
[
  {
    "role": "system",
    "content": "你是 SQLite Agent。根据真实工具 observation 决定下一步。"
  },
  {
    "role": "user",
    "content": "统计每位导演在 2000 年后执导的电影数。"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"list_tables\",\"arguments\":{}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"tables\":[\"Movie\",\"Rating\"]}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"get_schema\",\"arguments\":{\"table_names\":[\"Movie\"]}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"tables\":{\"Movie\":{\"columns\":[{\"name\":\"year\"},{\"name\":\"director\"}]}}}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"execute_sql\",\"arguments\":{\"sql\":\"SELECT director, COUNT(*) AS movie_count FROM Movie WHERE year > 2000 GROUP BY director\"}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"columns\":[\"director\",\"movie_count\"],\"rows\":[[\"James Cameron\",1],[\"Peter Jackson\",3]]}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"final\",\"final_sql\":\"SELECT director, COUNT(*) AS movie_count FROM Movie WHERE year > 2000 GROUP BY director\",\"answer\":\"James Cameron: 1; Peter Jackson: 3\"}"
  }
]
```

#### 构造流程

```text
困难任务候选
→ Teacher 自主选择工具
→ SQLite 执行动作并返回 observation
→ Teacher 继续生成，直到 final 或预算结束
→ verifier 执行 final_sql 并与 Gold Result 比较
→ 仅成功轨迹经过协议清洗后进入 SFT
```

第一批共有 3,760 个候选，2,167 条通过执行结果验证，2,053 条通过消息和协议清洗；JSON V2 转换时又因长度过滤删除 8 条，最终保留 2,045 条。这类数据比自动 Oracle 轨迹更接近真实决策，但“Teacher 来源”仍不保证每个中间动作都是最优。

正式样本：`spider_004170__teacher_agent__json_v2`。

### 4.5 `repair_real`：历史 Repair 来源与严格修复轨迹

#### 完整精简 `messages`

```json
[
  {
    "role": "system",
    "content": "你是 SQLite Agent。SQL 失败或结果不足时继续修改，不要提前 final。"
  },
  {
    "role": "user",
    "content": "列出 2000 年后由 James Cameron 执导的电影名。"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"get_schema\",\"arguments\":{\"table_names\":[\"Movie\"]}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"tables\":{\"Movie\":{\"columns\":[{\"name\":\"title\"},{\"name\":\"year\"},{\"name\":\"director\"}]}}}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"execute_sql\",\"arguments\":{\"sql\":\"SELECT * FROM Movie WHERE year > 2000 AND director = 'James Cameron'\"}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":false,\"error\":\"wrong_result\",\"verifier\":{\"pred_columns\":[\"mID\",\"title\",\"year\",\"director\"],\"gold_row_count\":1,\"pred_row_count\":1},\"instruction\":\"查询可以执行，但结果不匹配。修改 SQL 后继续。\"}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"execute_sql\",\"arguments\":{\"sql\":\"SELECT title FROM Movie WHERE year > 2000 AND director = 'James Cameron'\"}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"columns\":[\"title\"],\"rows\":[[\"Avatar\"]]}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"final\",\"final_sql\":\"SELECT title FROM Movie WHERE year > 2000 AND director = 'James Cameron'\",\"answer\":\"Avatar\"}"
  }
]
```

#### 构造流程

```text
第一次 Teacher rollout 失败
→ verifier 分类 parse/execution/wrong-result 等失败
→ 构造带 instruction 的失败 tool_result
→ 将原问题、必要 Schema、失败 SQL 和反馈组成 seed_messages
→ Teacher 从失败上下文继续生成
→ 只有最终 verifier 成功的轨迹才作为候选 Repair SFT
```

这里必须区分三件事：

1. **离线数据构造**会调用 SQLite 和 verifier，把失败反馈写进完整轨迹；
2. **SFT 训练**不会现场重试，轨迹已经固定，模型只是学习失败 observation 后应该输出什么；
3. **推理或 RL rollout**才由 runtime 执行动作、追加新的 observation，并让模型在线调整。

`wrong_result` 也不是 SQLite 自己能够即时判断的错误。SQLite 只能知道 SQL 是否可执行；结果语义是否正确，需要 verifier 与 Gold Result 比较。上例中的 `ok=false/wrong_result` 是数据构造阶段注入的结构化反馈。

#### 当前 251 条的实际审计

`repair_real` 是历史来源标签，不保证每条都包含严格 repair loop：

| 消息形态 | 数量 | 应怎样理解 |
|---|---:|---|
| 明确出现失败 observation，随后继续动作 | 142 | 严格意义的 Repair 监督 |
| 没有显式失败，但有多次 `execute_sql` | 33 | 迭代修正或继续探索 |
| 没有失败且只执行一次 SQL | 76 | 历史粗粒度标签下的普通成功轨迹 |
| **合计** | **251** | 不能整体称为 251 条标准 Repair |

正式样本：`spider_005042__exec_repair_syntax_error_9__json_v2`。该样本包含真实执行错误；上面的精简示例则使用更容易理解的 `wrong_result` 展示同一消息结构。

### 4.6 `protocol_anchor`：短协议锚点

Protocol Anchor 不是一种新的任务来源，而是从已有轨迹中截取关键边界。正式数据包含三种形态：

| Anchor 形态 | 数量 | 截取位置 |
|---|---:|---|
| `first_tool` | 158 | 问题到第一次工具调用 |
| `execute_sql` | 155 | 保留生成第一条执行 SQL 所需的上下文 |
| `final` | 187 | 成功执行结果到 final |
| **合计** | **500** | 从 600 条候选中选取 |

#### 完整精简 `messages`：`first_tool`

```json
[
  {
    "role": "system",
    "content": "你是 SQLite Agent。每轮只输出一个 JSON 对象。"
  },
  {
    "role": "user",
    "content": "显示所有电子游戏类型。"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"list_tables\",\"arguments\":{}}"
  }
]
```

#### 完整精简 `messages`：`execute_sql`

```json
[
  {
    "role": "system",
    "content": "你是 SQLite Agent。每轮只输出一个 JSON 对象。"
  },
  {
    "role": "user",
    "content": "显示工资至少为 100000 的员工编号。"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"get_schema\",\"arguments\":{\"table_names\":[\"Employee\"]}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"tables\":{\"Employee\":{\"columns\":[{\"name\":\"eid\"},{\"name\":\"salary\"}]}}}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"execute_sql\",\"arguments\":{\"sql\":\"SELECT eid FROM Employee WHERE salary >= 100000\"}}"
  }
]
```

#### 完整精简 `messages`：`final`

```json
[
  {
    "role": "system",
    "content": "你是 SQLite Agent。每轮只输出一个 JSON 对象。"
  },
  {
    "role": "user",
    "content": "统计位于 HHH 的俱乐部数量。"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"execute_sql\",\"arguments\":{\"sql\":\"SELECT COUNT(*) FROM Club WHERE ClubLocation = 'HHH'\"}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"columns\":[\"COUNT(*)\"],\"rows\":[[1]]}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"final\",\"final_sql\":\"SELECT COUNT(*) FROM Club WHERE ClubLocation = 'HHH'\",\"answer\":\"1\"}"
  }
]
```

#### 构造流程

```text
4,986 条 clean JSON 轨迹
→ 找出 first_tool / first execute_sql / successful-result-to-final 切片
→ 得到 600 条候选
→ 固定随机种子打乱并选择 500 条
```

Anchor 的目标是重复监督工具 JSON 和终止边界，不是增加新的 SQL 知识。正式样本：`spider_005973__teacher_agent__anchor_first_tool_4454`。

### 4.7 `teacher_agent_real_v3`：新一轮困难 Teacher 轨迹

#### 完整精简 `messages`

```json
[
  {
    "role": "system",
    "content": "你是 SQLite Agent。先检查真实 Schema，再完成困难多表查询。"
  },
  {
    "role": "user",
    "content": "找出订单总额高于所有客户平均订单总额的客户姓名。"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"list_tables\",\"arguments\":{}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"tables\":[\"customers\",\"orders\",\"order_items\"]}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"get_schema\",\"arguments\":{\"table_names\":[\"customers\",\"orders\",\"order_items\"]}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"tables\":{\"customers\":{\"columns\":[{\"name\":\"customer_id\"},{\"name\":\"name\"}]},\"orders\":{\"columns\":[{\"name\":\"order_id\"},{\"name\":\"customer_id\"}]},\"order_items\":{\"columns\":[{\"name\":\"order_id\"},{\"name\":\"amount\"}]}}}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"tool_call\",\"name\":\"execute_sql\",\"arguments\":{\"sql\":\"WITH totals AS (SELECT o.customer_id, SUM(i.amount) AS total FROM orders o JOIN order_items i ON o.order_id = i.order_id GROUP BY o.customer_id) SELECT c.name FROM customers c JOIN totals t ON c.customer_id = t.customer_id WHERE t.total > (SELECT AVG(total) FROM totals)\"}}"
  },
  {
    "role": "user",
    "content": "{\"type\":\"tool_result\",\"result\":{\"ok\":true,\"columns\":[\"name\"],\"rows\":[[\"Alice\"],[\"Chen\"]]}}"
  },
  {
    "role": "assistant",
    "content": "{\"type\":\"final\",\"final_sql\":\"WITH totals AS (SELECT o.customer_id, SUM(i.amount) AS total FROM orders o JOIN order_items i ON o.order_id = i.order_id GROUP BY o.customer_id) SELECT c.name FROM customers c JOIN totals t ON c.customer_id = t.customer_id WHERE t.total > (SELECT AVG(total) FROM totals)\",\"answer\":\"Alice; Chen\"}"
  }
]
```

#### 构造流程

```text
固定 Train 候选池中的困难英文任务
→ DeepSeek V4 Pro 在真实 SQLite runtime rollout
→ 去重后 620 条轨迹
→ 检查 messages、工具名、唯一 final 和执行结果
→ verifier 成功的 331 条转换为 teacher_agent_real_v3
→ 与 5,486 条基础数据合并为 5,817 条
```

这 331 条全部来自新批次困难、多表候选，用于补充 JOIN、嵌套查询和集合运算等复杂行为。与 `teacher_agent` 的核心方法相同，但采集批次、候选池、冻结 prompt 和构建脚本不同，因此单独保留 variant。

正式样本：`pool_003626__teacher_agent_real__json_v3`。

## 5. 七类数据如何协同

| 能力层 | 数据类型 | 主要贡献 |
|---|---|---|
| SQL 基础 | `sql_core` | 短路径 SQL 语义监督 |
| Oracle 工具基础 | `schema_only`、`agent_trace` | 稳定工具格式和标准成功流程 |
| 真实策略 | `teacher_agent`、`teacher_agent_real_v3` | observation 驱动的工具选择与复杂 SQL |
| 恢复与接口稳定 | `repair_real`、`protocol_anchor` | 失败后的下一动作、协议和终止边界 |

这不是让一种样本解决所有问题，而是用不同数据承担不同职责。完整历史见[《SFT 数据演进》](../项目演进/SFT数据演进.md)。

## 6. LoRA 训练

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

## 7. checkpoint 选择

训练 loss 只衡量 teacher forcing，不能代替真实 Agent rollout。checkpoint 同时比较协议、结束、可执行性、结果正确性、解析失败和超步数。现有记录选择 checkpoint-600；详细指标及证据等级见 [`results/sft/checkpoint600.summary.json`](../../results/sft/checkpoint600.summary.json)。

这些指标来自历史正式记录和 W&B run 元数据，并非仓库内重新执行产生的原始导出。它们证明该 checkpoint 在固定评测流程中的表现，不单独证明严格未见 Schema 泛化。

## 8. 复现入口

训练与评测命令见 [`sqlite_agent/scripts/sft/README.md`](../../sqlite_agent/scripts/sft/README.md)。评测 adapter 时必须同时指定基座模型、adapter、任务文件和协议，不能把 adapter 目录当作完整模型直接运行。
