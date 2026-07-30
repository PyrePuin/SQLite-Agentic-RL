# SQLite Agentic RL 数据

该目录是项目的数据根目录。任务文件中的路径均使用项目相对路径，因此
仓库可以在不同机器之间迁移。

## 正式 SFT 训练集

### 当前正式版本：V3 Real JSON

下一次 SFT 应使用：

- 训练文件：`data/sft/v3_real_json/sft_v3_real_json_5817.jsonl`
- 清单：`data/sft/v3_real_json/manifest.json`
- 审计：`data/sft/v3_real_json/audit.json`
- 协议：`json_v2`，assistant target 是纯 JSON，不含 XML 标签
- 当前行数：5,817

数据组成：

- V2 JSON 基础数据：5,486 条
- 通过验证的真实英文 Teacher Agent 困难轨迹：331 条

新增的 331 条数据来自 DeepSeek Teacher 在真实 SQLite 工具环境中的
rollout，并且通过了执行验证。它们不是由 Gold SQL 机械拼接出的固定轨迹。

关键审计结果：

- Assistant XML 标签：0
- Assistant 数据结构错误：0
- 非法工具名：0
- 真实 Teacher 轨迹覆盖：81 个数据库
- 真实 Teacher 轨迹难度：230 条困难，101 条中等

### 上一版 V2 JSON 基础数据

为了保证构造过程可复现，继续保留：

- 训练文件：`data/sft/v2_json/sft_v2_json_5486.jsonl`
- 当前行数：5,486
- 清单：`data/sft/v2_json/manifest.json`
- 审计：`data/sft/v2_json/audit.json`

## 验证集

所有验证集只从 `data/splits/v2_db_seed42/dev.jsonl` 构造。保留的
`final_eval.jsonl` 不参与 checkpoint 选择。

标准 V2 验证集：

- `data/eval/sft_v2_json/mini_dev.jsonl`：60 条，36 个数据库
- `data/eval/sft_v2_json/fast_dev.jsonl`：120 条，36 个数据库
- `data/eval/sft_v2_json/full_dev.jsonl`：300 条，36 个数据库

V3 英文困难小型验证集：

- `data/eval/sft_v2_json/hard_mini_dev_en.jsonl`：110 条，22 个数据库

困难小型验证集是任务评测数据，不是 Teacher 轨迹。应由 Agent evaluator
在真实 runtime 中运行模型 rollout。

## 命令执行位置

所有 SFT 命令均从仓库根目录执行：

```bash
cd SQLite-Agentic-RL
```
