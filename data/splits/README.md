# 数据划分

数据划分在生成 `data/pool/task_pool.filtered.jsonl` 后进行。

最重要的规则是：`train/dev/final_eval` 按完整 `db_id` 划分，而不是按单个
问题随机划分。这样可以避免同一个 SQLite 数据库同时出现在训练集和
评测集中。

## 当前划分

使用：

```text
v2_db_seed42/
```

文件说明：

- `train.jsonl`：用于构造 SFT 数据和后续 RL prompt 的训练池
- `dev.jsonl`：用于模型选择、调试和常规评测的验证池
- `final_eval.jsonl`：保留的最终评测池，不得用于 prompt 调整、SFT
  采样决策、RL 超参数选择或 checkpoint 选择
- `dev_smoke.jsonl`：用于快速检查解析器、工具和评测链路的小型开发集
- `split_manifest.json`：划分统计、数据库归属和重叠检查

当前规模：

| 划分 | 行数 | 数据库数 |
|---|---:|---:|
| 训练集 | 6,069 | 134 |
| 开发集 | 761 | 36 |
| 最终评测集 | 756 | 36 |
| 开发集冒烟子集 | 72 | 36 |

`split_manifest.json` 显示训练集、开发集和最终评测集之间不存在数据库重叠。

## 语言采样策略

划分文件保存底层任务。许多行同时包含 `question_zh` 和 `question_en`，
但划分阶段不决定最终使用哪种语言训练。

SFT 构造器以中文为主要分布，以英文作为辅助 grounding：

- 总体目标约为 80% 中文 CSpider 风格问题、20% 英文 Spider 风格问题
- 对中英文配对任务，默认选择中文问题
- 只为约 20%～25% 的配对任务额外采样英文版本
- 不要把每条配对任务都复制成中英文两个样本

这样可以保持目标场景：中文用户问题、英文表名和列名、英文 SQLite
错误信息，以及中文系统与工具说明。

## 重建命令

从项目根目录执行：

```bash
python3 sqlite_agent/scripts/data/make_splits.py \
  --input data/pool/task_pool.filtered.jsonl \
  --output-dir data/splits/v2_db_seed42 \
  --seed 42 \
  --train-frac 0.80 \
  --dev-frac 0.10 \
  --smoke-per-db 2 \
  --smoke-max-rows 128
```
