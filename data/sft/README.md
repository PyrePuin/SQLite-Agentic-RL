# SFT 数据

该目录保存 JSON 协议 SFT 数据：`v2_json/` 提供基础数据与构造审计，
`v3_real_json/` 提供当前推荐的正式训练集。

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

## `v2_json/`：基础 JSON 协议数据

| 文件 | 作用 |
|---|---|
| `converted_clean_4986.jsonl` | 归一化为纯 JSON 协议并过滤 14 条长度异常样本后的结果 |
| `protocol_anchors_600.jsonl` | 600 条协议锚点候选，用于强化工具调用与 final JSON 格式 |
| `sft_v2_json_5486.jsonl` | 4,986 条清洗数据与选中的 500 条协议锚点组成的 V2 正式基础集 |
| `manifest.json` | 输入、输出、采样数量和构造参数 |
| `audit.json` | 协议合法性、类别分布、消息长度和被过滤样本审计 |

该目录适合审计基础数据组成、协议锚点和长度过滤规则。正式训练默认使用
`v3_real_json/` 中的 5,817 条数据。

## `v3_real_json/`：当前正式 SFT 数据

| 文件 | 作用 |
|---|---|
| `sft_v3_real_json_5817.jsonl` | 当前正式训练集，5,817 条 |
| `manifest.json` | 数据组成、协议、类别、工具调用和 Teacher 轨迹统计 |
| `audit.json` | 正式文件的结构与质量审计，`bad_examples` 当前为空 |
| `fixes_20260706.json` | 两条 `tool_call name=final` 被规范为正式 `final` 对象的修复审计 |
| `system_prompt_20260706.txt` | 冻结 Teacher 转换时使用的 system prompt，防止 runtime prompt 演进破坏逐字节复现 |

正式数据具有以下约束：

- assistant target 为单个纯 JSON 对象，不使用 XML 标签；
- 工具名仅允许 `list_tables`、`get_schema`、`preview_rows`、`execute_sql`；
- 331 条 `teacher_agent_real_v3` 均来自真实工具环境且通过 verifier；
- 训练文件已经包含两条后处理协议修复。

## 正式数据由什么组成

| 类型 | 数量 | 大概内容 |
|---|---:|---|
| `teacher_agent` | 2,045 | Teacher 生成的多轮工具调用示范，学习常规 Agent 解题流程 |
| `sql_core` | 1,100 | schema 与问题到 Gold SQL 的直接映射，稳住 SQL 基础能力 |
| `agent_trace` | 876 | 展开后的工具调用轨迹，学习查询数据库再作答的顺序 |
| `schema_only` | 714 | 以 schema 理解为主的样本，强化表、列和关系识别 |
| `protocol_anchor` | 500 | 强化 JSON tool call 与 final 输出格式的协议锚点 |
| `repair_real` | 251 | 基于真实错误整理的修复样本，学习从失败 SQL 或错误反馈中纠正 |
| `teacher_agent_real_v3` | 331 | Teacher 在真实 SQLite runtime 中执行并经 verifier 验证成功的困难多表轨迹 |
| **合计** | **5,817** | 当前正式训练文件 |

这不是七个互斥能力模块的简单拼接，而是“SQL 基础能力 + schema grounding + Agent 工具协议 + 多轮轨迹 + 错误修复”的混合训练配方。整个文件统一为 `json_v2` 协议，共包含 16,182 个 assistant 工具调用 target 和 5,506 个 final target。

## 构造脚本的边界

仓库已经发布可直接使用的正式文件 `v3_real_json/sft_v3_real_json_5817.jsonl`，以及相应 manifest、audit 和 Teacher 来源。因此，训练、审计和 331 条真实 Teacher 增量的转换可以直接运行。

仓库**没有提供从 Spider/CSpider 原始任务开始、逐条重建历史 5,486 条基础 SFT 的完整构造脚本**。现有脚本可以构造新的 SQL core、采集新的 Teacher rollout，并重建公开的 331 条 Teacher 增量，但不能承诺从零逐字节生成相同的 5,817 条文件。实验复现请直接使用已发布正式集；研究新数据配方时，再按 [`sqlite_agent/scripts/sft/README.md`](../../sqlite_agent/scripts/sft/README.md) 的运行链路生成新版本。

## 使用方式

运行正式 SFT：

```bash
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
  --bf16 \
  --wandb-run-name sqlite_sft_formal
```

训练前建议检查：

```bash
wc -l data/sft/v3_real_json/sft_v3_real_json_5817.jsonl
python -m json.tool data/sft/v3_real_json/manifest.json >/dev/null
python -m json.tool data/sft/v3_real_json/audit.json >/dev/null
```

构造或修改 SFT 数据后，应同时检查对应的 `manifest.json` 和
`audit.json`，不能只比较 JSONL 行数。

更完整的训练前检查、LoRA 训练、Agent 评测和 Teacher 构造命令见 [`sqlite_agent/scripts/sft/README.md`](../../sqlite_agent/scripts/sft/README.md)。
