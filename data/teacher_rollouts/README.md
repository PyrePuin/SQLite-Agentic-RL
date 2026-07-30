# Teacher Rollout 数据

该目录保存困难英文任务的候选池，以及 Teacher 模型在真实 SQLite Agent runtime 中产生的原始轨迹。这里的原始 rollout 是权威来源；SFT 使用的 331 条成功样本可由它重新转换。

## 三个文件

### `hard_train_pool_en_large_20260706.jsonl`

Teacher rollout 的候选任务池：

- 从 `data/splits/v2_db_seed42/train.jsonl` 选择；
- 仅保留有英文问题的任务；
- 优先多表、聚合、嵌套查询、集合操作和排序限制等较难任务；
- 共 1,000 条，覆盖 92 个数据库，每个数据库最多 20 条。

它只包含任务、Gold SQL、Gold Result、数据库路径和难度特征，不包含模型生成轨迹。

### `hard_train_pool_en_large_20260706.manifest.json`

上述候选池的构造清单，记录：

- 输入和输出路径；
- 目标行数、实际行数及数据库覆盖；
- 语言模式和单数据库采样上限；
- 多表、聚合、嵌套/集合操作、排序/限制等特征统计。

该文件用于确认候选池能否被复现，不参与模型训练。

### `hard_teacher_v4pro_en_all_dedup_20260706.jsonl`

DeepSeek V4 Pro 对候选任务执行后的真实 Agent rollout：

- 共 620 条去重轨迹，覆盖 86 个数据库；
- 331 条通过 verifier，289 条未通过；
- 每行保留任务信息、模型工具调用轨迹、最终回答、执行验证、错误信息和耗时；
- 成功与失败轨迹都保留，便于复查 Teacher 质量和失败模式。

正式 SFT 只吸收其中 331 条 `success=true` 的轨迹。

## 使用方式

将成功轨迹转换为 SFT JSONL：

```bash
python sqlite_agent/scripts/sft/build_sft_from_teacher_rollouts.py \
  --input data/teacher_rollouts/hard_teacher_v4pro_en_all_dedup_20260706.jsonl \
  --output outputs/teacher_sft_331.jsonl \
  --manifest outputs/teacher_sft_331.manifest.json
```

转换脚本使用 `data/sft/v3_real_json/system_prompt_20260706.txt` 中冻结的
system prompt，输出应为 331 条，并与正式 SFT 中的
`teacher_agent_real_v3` 子集一致。

检查输出：

```bash
wc -l outputs/teacher_sft_331.jsonl
python -m json.tool outputs/teacher_sft_331.manifest.json
```

## 数据角色

```text
1,000 条困难英文候选任务
          ↓ Teacher 实际执行
620 条去重 rollout
          ├── 331 条 verifier 成功 → 转换并并入正式 SFT
          └── 289 条失败 → 用于错误分析，不进入正式 SFT
```
