# 原始数据下载与处理

该目录保存 Spider 1.0、CSpider 1.0 的原始任务和 SQLite 数据库。由于文件
体积较大，并且需要遵守上游数据集许可证，`data/raw/` 中的实际数据不会
提交到 Git；仓库只跟踪本说明文件。

> 本项目使用 Spider 1.0，而不是 Spider 2.0。

## 1. 官方下载地址

### Spider 1.0

- [Spider 官方项目页](https://yale-lily.github.io/spider)
- [Spider 官方数据下载（Google Drive）](https://drive.google.com/file/d/1403EGqzIDoHMdQF4c9Bkyl7dZLZ5Wt6J/view?usp=sharing)
- [Spider 官方代码与评测脚本](https://github.com/taoyds/spider)
- 许可证：[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)

官方下载包通常名为 `spider_data.zip`，其中应包含：

```text
train_spider.json
dev.json
tables.json
database/
```

本项目当前使用 `train_spider.json` 的 7,000 条英文任务作为 Spider
来源。

### CSpider 1.0

- [CSpider 官方项目页](https://taolusi.github.io/CSpider-explorer/)
- [CSpider 官方数据下载（Google Drive）](https://drive.google.com/drive/folders/1TxCUq1ydPuBdDdHF3MkHT-8zixluQuLa?usp=sharing)
- [CSpider 官方数据下载（百度网盘）](https://pan.baidu.com/s/1B84p7Wl8jx9F3nd0xpt4hw)，项目页当前标注提取码 `9gzb`
- [CSpider 官方代码与评测脚本](https://github.com/taolusi/chisp)
- 许可证：[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)

CSpider 是 Spider 的中文翻译版本：问题主要为中文，表名、列名和 SQL
仍以英文为主。完整下载内容应包含：

```text
CSpider/
├── train.json
├── dev.json
├── tables.json
├── database/
├── test_data/
│   ├── test.json
│   └── tables_test.json
└── test_database/
    └── database.tar.gz
```

如果 Google Drive 或百度网盘目录结构发生变化，以
[CSpider 官方项目页](https://taolusi.github.io/CSpider-explorer/) 当前
公布的链接和提取码为准，不要使用来源不明的二次打包数据。

## 2. 推荐的本地目录

从仓库根目录开始：

```bash
mkdir -p data/raw/spider/source/downloads
mkdir -p data/raw/spider/source/extracted
mkdir -p data/raw/cspider/source/downloads
mkdir -p data/raw/cspider/source/extracted
```

下载并解压后，整理成：

```text
data/raw/
├── spider/
│   └── source/
│       ├── downloads/
│       │   └── spider_data.zip
│       └── extracted/
│           └── spider/
│               ├── train_spider.json
│               ├── dev.json
│               ├── tables.json
│               └── database/
└── cspider/
    └── source/
        ├── downloads/
        └── extracted/
            └── full_CSpider/
                └── CSpider/
                    ├── train.json
                    ├── dev.json
                    ├── tables.json
                    ├── database/
                    ├── test_data/
                    └── test_database/
```

Spider 可以直接解压：

```bash
unzip data/raw/spider/source/downloads/spider_data.zip \
  -d data/raw/spider/source/extracted/
```

不同版本的 ZIP 可能多一层目录。只要将下面命令中的 `SPIDER_SOURCE`
指向同时包含 `train_spider.json`、`tables.json` 和 `database/` 的目录
即可。

CSpider 的测试数据库可能仍是压缩包，需要额外解压：

```bash
CSPIDER_SOURCE=data/raw/cspider/source/extracted/full_CSpider/CSpider

tar -xzf "$CSPIDER_SOURCE/test_database/database.tar.gz" \
  -C "$CSPIDER_SOURCE/test_database"
```

## 3. 处理总流程

```text
官方 Spider / CSpider
→ 解压任务文件和 SQLite 数据库
→ 归一化为统一 JSONL 任务结构
→ 将绝对路径转换为仓库相对路径
→ 合并中英文任务并按 SQL 去重
→ 执行 Gold SQL，缓存 Gold Result
→ 过滤不可执行、过慢或结果过大的任务
→ 按完整 db_id 重新划分 train/dev/final_eval
```

所有命令都应从仓库根目录执行：

```bash
cd SQLite-Agentic-RL
export PYTHONPATH="$PWD/sqlite_agent:${PYTHONPATH:-}"
```

## 4. 归一化 Spider

设置解压后的 Spider 根目录：

```bash
SPIDER_SOURCE=data/raw/spider/source/extracted/spider
```

生成标准任务、清单，并把数据库复制到 `data/raw/spider/database/`：

```bash
python sqlite_agent/scripts/data/normalize_raw_datasets.py \
  --dataset spider \
  --input "$SPIDER_SOURCE/train_spider.json" \
  --db-root "$SPIDER_SOURCE/database" \
  --tables "$SPIDER_SOURCE/tables.json" \
  --output-dir data/raw \
  --split all \
  --task-prefix spider \
  --copy-databases
```

输出：

```text
data/raw/spider/tasks_all.jsonl
data/raw/spider/manifest_all.json
data/raw/spider/database/
```

预期规模是 7,000 条任务、140 个数据库。

## 5. 归一化 CSpider

```bash
CSPIDER_SOURCE=data/raw/cspider/source/extracted/full_CSpider/CSpider
```

分别处理训练集、开发集和已公开测试集：

```bash
python sqlite_agent/scripts/data/normalize_raw_datasets.py \
  --dataset cspider \
  --input "$CSPIDER_SOURCE/train.json" \
  --db-root "$CSPIDER_SOURCE/database" \
  --tables "$CSPIDER_SOURCE/tables.json" \
  --output-dir data/raw \
  --split train \
  --task-prefix cspider_train

python sqlite_agent/scripts/data/normalize_raw_datasets.py \
  --dataset cspider \
  --input "$CSPIDER_SOURCE/dev.json" \
  --db-root "$CSPIDER_SOURCE/database" \
  --tables "$CSPIDER_SOURCE/tables.json" \
  --output-dir data/raw \
  --split dev \
  --task-prefix cspider_dev

python sqlite_agent/scripts/data/normalize_raw_datasets.py \
  --dataset cspider \
  --input "$CSPIDER_SOURCE/test_data/test.json" \
  --db-root "$CSPIDER_SOURCE/test_database" \
  --tables "$CSPIDER_SOURCE/test_data/tables_test.json" \
  --output-dir data/raw \
  --split test \
  --task-prefix cspider_test
```

输出及预期规模：

| 文件 | 任务数 | 数据库数 |
|---|---:|---:|
| `data/raw/cspider/tasks_train.jsonl` | 8,659 | 146 |
| `data/raw/cspider/tasks_dev.jsonl` | 1,034 | 20 |
| `data/raw/cspider/tasks_test.jsonl` | 2,147 | 40 |

## 6. 路径相对化

归一化脚本需要通过绝对路径找到真实数据库，因此最初写入的 `db_path`
可能包含当前机器目录。进入任务池前必须转换为仓库相对路径：

```bash
python sqlite_agent/scripts/data/relativize_paths.py \
  data/raw/spider \
  data/raw/cspider
```

转换示例：

```text
/workspace/SQLite-Agentic-RL/data/raw/spider/database/.../db.sqlite
→ data/raw/spider/database/.../db.sqlite
```

路径工具同时兼容旧目录名 `SQLite-Agentic-RL-V2`，用于迁移历史数据。

## 7. 检查归一化结果

```bash
python sqlite_agent/scripts/data/inspect_raw_datasets.py \
  data/raw/spider/tasks_all.jsonl \
  data/raw/cspider/tasks_train.jsonl \
  data/raw/cspider/tasks_dev.jsonl \
  data/raw/cspider/tasks_test.jsonl
```

重点检查：

- 任务数量和数据库数量是否符合预期
- `question`、`gold_sql`、`db_path` 是否缺失
- 每个 `db_path` 是否能定位到真实 SQLite 文件
- Spider 为 `language=en`，CSpider 为 `language=zh`

标准任务结构如下：

```json
{
  "task_id": "spider_000000",
  "dataset": "spider",
  "language": "en",
  "db_id": "department_management",
  "db_path": "data/raw/spider/database/department_management/department_management.sqlite",
  "question": "How many heads of the departments are older than 56 ?",
  "table_names": ["department", "head", "management"],
  "gold_sql": "SELECT count(*) FROM head WHERE age > 56"
}
```

## 8. 构建统一任务池

本项目将 Spider 英文任务和 CSpider 中英文任务放入统一候选池，按
`(db_id, normalized_gold_sql)` 去重：

```bash
python sqlite_agent/scripts/data/build_task_pool.py \
  --input data/raw/spider/tasks_all.jsonl \
  --input data/raw/cspider/tasks_train.jsonl \
  --input data/raw/cspider/tasks_dev.jsonl \
  --input data/raw/cspider/tasks_test.jsonl \
  --output data/pool/intermediate/task_pool.raw.jsonl \
  --manifest data/pool/task_pool.raw.manifest.json
```

同一 SQL 的中英文问题会合并到一行的 `question_en`、`question_zh` 和
`sources` 中。

## 9. 执行 Gold SQL 并过滤

```bash
python sqlite_agent/scripts/data/cache_and_filter_task_pool.py \
  --input data/pool/intermediate/task_pool.raw.jsonl \
  --with-gold-output data/pool/intermediate/task_pool.with_gold.jsonl \
  --filtered-output data/pool/task_pool.filtered.jsonl \
  --manifest data/pool/task_pool.filter.manifest.json \
  --max-rows 500 \
  --max-sql-length 1200 \
  --timeout-sec 5.0
```

过滤条件：

- 只允许只读 `SELECT` / `WITH`
- Gold SQL 必须成功执行
- 结果行数不超过 500
- SQL 长度不超过 1,200
- 执行时间不超过 5 秒

当前构建结果为 7,586 条有效任务、206 个数据库。

## 10. 按数据库重新划分

```bash
python sqlite_agent/scripts/data/make_splits.py \
  --input data/pool/task_pool.filtered.jsonl \
  --output-dir data/splits/v2_db_seed42 \
  --seed 42 \
  --train-frac 0.80 \
  --dev-frac 0.10 \
  --smoke-per-db 2 \
  --smoke-max-rows 128
```

划分单位是完整 `db_id`，同一个数据库不会跨训练集、开发集和最终评测集。
生成：

```text
data/splits/v2_db_seed42/train.jsonl
data/splits/v2_db_seed42/dev.jsonl
data/splits/v2_db_seed42/final_eval.jsonl
data/splits/v2_db_seed42/dev_smoke.jsonl
data/splits/v2_db_seed42/split_manifest.json
```

最后再统一检查并清理派生文件中的机器绝对路径：

```bash
python sqlite_agent/scripts/data/relativize_paths.py \
  data/pool \
  data/splits
```

## 11. 评测口径说明

本项目不是直接复现 Spider/CSpider 官方 train/dev/test leaderboard
划分，而是把已公开的数据放入统一任务池，再按完整数据库重新建立内部
`train/dev/final_eval`。

因此：

- 项目中的 `final_eval` 是内部数据库级保留集
- 项目结果不能表述为 Spider 或 CSpider 官方隐藏测试集成绩
- 如果要与官方 leaderboard 比较，必须另行保留官方划分，并使用官方
  评测脚本
