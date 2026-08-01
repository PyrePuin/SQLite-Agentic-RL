# SFT 数据、训练与评测运行指南

本目录覆盖 SQL core 构造、Teacher Agent rollout、失败审计、LoRA SFT 和真实 Agent 评测。所有命令均从仓库根目录执行：

```bash
cd SQLite-Agentic-RL
python -m pip install -e '.[sft,data,dev]'
export PYTHONPATH="$PWD/sqlite_agent:${PYTHONPATH:-}"
```

## 正式 SFT 数据是什么

当前正式训练文件已经随仓库发布：

```text
data/sft/v3_real_json/sft_v3_real_json_5817.jsonl
```

它包含 5,817 条 JSON V2 SFT 样本：

| 类型 | 数量 | 大致内容 |
|---|---:|---|
| `teacher_agent` | 2,045 | 早期 Teacher 多轮工具轨迹，学习 schema 探索、SQL 执行和结束 |
| `sql_core` | 1,100 | 给定 schema 与问题，直接监督 Gold SQL，保持基础 SQL 能力 |
| `agent_trace` | 876 | 工具调用、observation 与下一动作组成的多轮 Agent 轨迹 |
| `schema_only` | 714 | 识别相关表和字段，学习 schema 理解与动作选择 |
| `protocol_anchor` | 500 | 短小的 canonical JSON tool call/final 样本，稳定输出协议 |
| `repair_real` | 251 | SQL 执行失败、SQLite error observation 和修正动作 |
| `teacher_agent_real_v3` | 331 | DeepSeek V4 Pro 在真实 SQLite Runtime 中执行且 verifier 成功的轨迹 |

最终文件中共有 16,182 个 assistant tool-call target 和 5,506 个 final target，全部使用 `json_v2`；XML 标签、非法工具名和 assistant schema 错误均为 0。

### 构造边界

5,817 条数据由两层组成：

```text
历史数据迁移、清洗和协议转换得到的冻结基础集 5,486
+ 新采集且 verifier 成功的 Teacher 轨迹 331
= 正式 SFT 5,817
```

仓库已经发布 5,486 条基础集、331 条原始 Teacher 成功来源和最终 5,817 条正式文件，因此用户可以直接训练和审计。但仓库**没有保留从 Spider/CSpider 任务池完整重建历史 5,486 条基础集的全部原始构造脚本与中间来源**：现有 archive 脚本只能复现部分早期方案或协议迁移，不能宣称从零逐字节重建整个基础集。

可精确追溯的部分包括：

- `data/sft/v2_json/sft_v2_json_5486.jsonl`：已发布的冻结基础集；
- `data/teacher_rollouts/hard_teacher_v4pro_en_all_dedup_20260706.jsonl`：620 条去重 Teacher rollout；
- `build_sft_from_teacher_rollouts.py`：从其中 331 条 success 轨迹重建正式 Teacher 增量；
- `data/sft/v3_real_json/manifest.json` 与 `audit.json`：最终组成和协议审计。

如果目标是复现实验结果，应直接使用已发布的 5,817 条正式文件；如果目标是研究新的数据配方，可以使用下面的 SQL core 与 Teacher 脚本重新构造新数据，但新结果不应继续称为原始 5,817 条数据。

## 当前 JSON 协议

- Assistant 工具调用：`{"type":"tool_call","name":"execute_sql","arguments":{"sql":"SELECT ..."}}`
- User 工具结果：`{"type":"tool_result","result":{"ok":true,...}}`
- Assistant 最终输出：`{"type":"final","final_sql":"SELECT ...","answer":"..."}`

`sql_core` 是独立的直接 SQL 模式，assistant content 是 SQL 字符串，不经过四工具 Agent 协议。

## 运行链路 A：直接使用正式数据训练

这是复现当前 SFT 结果的推荐路径：

```text
检查正式文件与 manifest
→ inspect_sft_token_lengths.py
→ run_formal_sft_eval.py
→ evaluate_sft_v2_agent.py（按需单独复评）
→ cleanup_sft_run.py（确认最佳点后）
```

### 1. 检查数据

```bash
wc -l data/sft/v3_real_json/sft_v3_real_json_5817.jsonl
python -m json.tool data/sft/v3_real_json/manifest.json >/dev/null
python -m json.tool data/sft/v3_real_json/audit.json >/dev/null
```

预期行数为 5,817，`audit.json` 中 `bad_examples` 为空。

### 2. 检查 token 长度

```bash
BASE_MODEL=/path/to/Qwen2.5-Coder-3B-Instruct

python sqlite_agent/scripts/sft/inspect_sft_token_lengths.py \
  --model "$BASE_MODEL" \
  --input data/sft/v3_real_json/sft_v3_real_json_5817.jsonl \
  --max-length 2048 \
  --output outputs/sft/token_length_summary.json \
  --local-files-only
```

重点查看整体和各 variant 的 `over_max_length_rate`，确认截断不会集中破坏某一类轨迹。

### 3. 正式训练与固定步数评测

```bash
python sqlite_agent/scripts/sft/run_formal_sft_eval.py \
  --model "$BASE_MODEL" \
  --train-data data/sft/v3_real_json/sft_v3_real_json_5817.jsonl \
  --mini-dev data/eval/mini_dev.jsonl \
  --fast-dev data/eval/fast_dev.jsonl \
  --full-dev data/eval/full_dev.jsonl \
  --output-dir checkpoints/qwen25_coder3b_sqlite_sft_v3_real_json_formal \
  --epochs 2 \
  --train-samples 5817 \
  --effective-batch-size 16 \
  --eval-every-steps 100 \
  --max-length 2048 \
  --learning-rate 1e-4 \
  --lora-rank 32 \
  --lora-alpha 64 \
  --per-device-train-batch-size 1 \
  --gradient-accumulation-steps 16 \
  --bf16 \
  --local-files-only \
  --wandb-project sqlite-agentic-rl-v2 \
  --wandb-run-name sft_v3_real_json_coder3b_formal
```

`run_formal_sft_eval.py` 是正式总入口。它调用 `train_sft_v2_lora.py` 连续训练，并在固定 global step 暂停调用 `evaluate_sft_v2_agent.py`，不会重置 optimizer 或 cosine scheduler。

### 4. 单独评测 checkpoint

```bash
python sqlite_agent/scripts/sft/evaluate_sft_v2_agent.py \
  --base-model "$BASE_MODEL" \
  --adapter checkpoints/qwen25_coder3b_sqlite_sft_v3_real_json_formal/checkpoint-600 \
  --tasks data/eval/full_dev.jsonl \
  --output outputs/sft/full_dev_checkpoint600.jsonl \
  --summary-output outputs/sft/full_dev_checkpoint600.summary.json \
  --max-tool-steps 8 \
  --max-new-tokens 192 \
  --max-prompt-tokens 4096 \
  --protocol json_v2 \
  --local-files-only
```

checkpoint 选择优先比较 strict/equivalent、SQL 可执行率、finalization、canonical protocol、parse failed 和 budget exceeded，而不是只看训练 loss。当前正式选择是 `checkpoint-600`。

### 5. 确认后清理中间 checkpoint

先预览，不会删除：

```bash
python sqlite_agent/scripts/sft/cleanup_sft_run.py \
  --run-dir checkpoints/qwen25_coder3b_sqlite_sft_v3_real_json_formal \
  --keep-checkpoints 600 \
  --keep-final \
  --delete-partial-rollouts \
  --dry-run
```

确认列表无误后去掉 `--dry-run`。该脚本会删除未保留的 checkpoint，属于破坏性收尾操作，不应在模型选择前执行。

## 运行链路 B：重建 331 条 Teacher 增量

这条链用于理解和复查真实 Teacher 数据，不会重建历史 5,486 条基础集：

```text
已发布困难候选池
→ collect_teacher_rollouts.py
→ judge_rollout_audit.py
→ build_rollout_buckets.py
→ build_sft_from_teacher_rollouts.py
→ 与正式 Teacher 子集对比
```

### 1. 候选任务

项目已经发布：

```text
data/teacher_rollouts/hard_train_pool_en_large_20260706.jsonl
```

它包含 1,000 条困难英文任务、覆盖 92 个数据库。正式仓库没有保留该候选池的独立一键构造脚本，因此这条重建链以已发布候选池为起点。

### 2. 调用 Teacher 采集真实轨迹

脚本使用 DeepSeek OpenAI-compatible API，需要设置 API Key：

```bash
export DEEPSEEK_API_KEY='your-api-key'
mkdir -p outputs/teacher

python sqlite_agent/scripts/sft/collect_teacher_rollouts.py \
  --input data/teacher_rollouts/hard_train_pool_en_large_20260706.jsonl \
  --output outputs/teacher/teacher_rollouts.jsonl \
  --model deepseek-v4-pro \
  --language-mode en_only \
  --limit 1000 \
  --max-steps 10 \
  --temperature 0 \
  --reasoning-effort medium \
  --timeout-sec 120 \
  --max-retries 2 \
  --workers 1 \
  --resume
```

`--resume` 会跳过输出文件中已经完成的 task id。提高 `--workers` 会加快采集，但也会提高并发请求、限流和费用风险。Teacher 服务和模型版本会变化，因此重新调用 API 不保证得到历史的 620/331 结果；精确复查应使用仓库已发布的原始 rollout 文件。

### 3. 审计失败轨迹

```bash
python sqlite_agent/scripts/sft/judge_rollout_audit.py \
  --input outputs/teacher/teacher_rollouts.jsonl \
  --output outputs/teacher/teacher_audit.jsonl \
  --model deepseek-v4-pro \
  --strict-fail-only \
  --timeout-sec 120 \
  --max-retries 2
```

LLM judge 只帮助区分真实语义错误、可疑标签冲突和不确定样本，不替代 SQLite execution verifier。

### 4. 生成错误分桶

```bash
python sqlite_agent/scripts/sft/build_rollout_buckets.py \
  --rollouts outputs/teacher/teacher_rollouts.jsonl \
  --audit outputs/teacher/teacher_audit.jsonl \
  --output outputs/teacher/teacher_rollouts.bucketed.jsonl \
  --bucket-dir outputs/teacher/buckets \
  --manifest outputs/teacher/buckets.manifest.json
```

分桶包括 strict pass、协议失败、无法结束、执行失败、语义错误、标签冲突、结果等价和不确定样本。只有经过明确质量门控的轨迹才适合进入正向 SFT。

### 5. 转换 success 轨迹

若要精确重建项目使用的 331 条增量，应直接使用已发布的 620 条历史 rollout：

```bash
python sqlite_agent/scripts/sft/build_sft_from_teacher_rollouts.py \
  --input data/teacher_rollouts/hard_teacher_v4pro_en_all_dedup_20260706.jsonl \
  --output outputs/teacher/teacher_sft_331.jsonl \
  --manifest outputs/teacher/teacher_sft_331.manifest.json

wc -l outputs/teacher/teacher_sft_331.jsonl
pytest -q tests/test_teacher_rollout_conversion.py
```

转换器只接收 `success=true` 且消息结构完整的轨迹，并使用冻结的 `system_prompt_20260706.txt`。预期输出 331 条，测试会验证它与正式 5,817 条文件中的 `teacher_agent_real_v3` 子集一致。

仓库目前没有提供把任意新 Teacher 输出自动合并成一个新“正式 SFT”并完成全部审计的一键脚本。不要只用文件拼接就覆盖已发布的正式数据；新配方应写入 `outputs/`，独立记录 manifest、去重和协议审计。

## 可选：构造新的 SQL core 数据

```bash
python sqlite_agent/scripts/sft/build_sql_core.py \
  --input data/splits/v2_db_seed42/train.jsonl \
  --output-jsonl outputs/sft/sql_core.jsonl \
  --output-parquet outputs/sft/sql_core.parquet \
  --limit 1100 \
  --seed 42 \
  --english-rate 0.20
```

它会读取 Gold 涉及表的真实 schema，把问题与 schema 作为输入、Gold SQL 作为 assistant target。该命令适合构造新实验数据，但不能单独重建完整 5,817 条正式集。

早期混合构造、XML→JSON 迁移和机械增强消融见 [`../archive/sft/README.md`](../archive/sft/README.md)。
