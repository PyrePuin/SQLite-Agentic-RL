# SFT 数据

该目录保存两代仍有价值的 JSON 协议数据：`v2_json/` 用于保留基础数据的构造过程，`v3_real_json/` 是当前正式训练版本。

## 目录关系

```text
v2_json/sft_v2_json_5486.jsonl
    5,486 条基础数据
              +
Teacher rollout 中 331 条 verifier 成功轨迹
              ↓
v3_real_json/sft_v3_real_json_5817.jsonl
    5,817 条正式训练数据
```

原先保存 331 条转换结果的 `v3_json/` 已删除：它已被正式文件完整包含，并且能从 `data/teacher_rollouts/hard_teacher_v4pro_en_all_dedup_20260706.jsonl` 重新生成。

## `v2_json/`：基础 JSON 协议数据

| 文件 | 作用 |
|---|---|
| `converted_clean_4986.jsonl` | 旧数据归一化为纯 JSON 协议并删除 14 条长度异常样本后的结果 |
| `protocol_anchors_600.jsonl` | 600 条协议锚点候选，用于强化工具调用与 final JSON 格式 |
| `sft_v2_json_5486.jsonl` | 4,986 条清洗数据与选中的 500 条协议锚点组成的 V2 正式基础集 |
| `manifest.json` | 输入、输出、采样数量和构造参数 |
| `audit.json` | 协议合法性、类别分布、消息长度和被过滤样本审计 |

`v2_json/` 不再作为下一次正式训练的首选输入，但它保留了从基础数据到最终 V3 Real 的可解释构造链路。

## `v3_real_json/`：当前正式 SFT 数据

| 文件 | 作用 |
|---|---|
| `sft_v3_real_json_5817.jsonl` | 当前正式训练集，5,817 条 |
| `manifest.json` | 数据组成、协议、类别、工具调用和 Teacher 轨迹统计 |
| `audit.json` | 正式文件的结构与质量审计，`bad_examples` 当前为空 |
| `fixes_20260706.json` | 两条历史 `tool_call name=final` 被规范为正式 `final` 对象的修复记录 |
| `system_prompt_20260706.txt` | 冻结 Teacher 转换时使用的 system prompt，防止 runtime prompt 演进破坏逐字节复现 |

正式数据具有以下约束：

- assistant target 为单个纯 JSON 对象，不使用 XML 标签；
- 工具名仅允许 `list_tables`、`get_schema`、`preview_rows`、`execute_sql`；
- 331 条 `teacher_agent_real_v3` 均来自真实工具环境且通过 verifier；
- 训练文件已经包含两条后处理协议修复。

## 正式训练输入

```text
data/sft/v3_real_json/sft_v3_real_json_5817.jsonl
```

构造或修改 SFT 数据后，应同时检查对应的 `manifest.json` 和 `audit.json`，不能只比较 JSONL 行数。
