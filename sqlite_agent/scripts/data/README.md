# 数据处理脚本

这些脚本把 Spider/CSpider 原始文件转换为可执行、可拆分的统一任务池。所有命令均从仓库根目录执行。

| 脚本 | 输入 → 输出 |
|---|---|
| `normalize_raw_datasets.py` | 上游 JSON、tables、database → 标准任务 JSONL 与数据库目录 |
| `relativize_paths.py` | 含绝对路径的任务/manifest → 仓库相对路径 |
| `inspect_raw_datasets.py` | 标准任务 JSONL → 数据规模与字段检查报告 |
| `build_task_pool.py` | Spider/CSpider 任务 → 合并去重的 raw pool |
| `cache_and_filter_task_pool.py` | raw pool → Gold Result 缓存与 filtered pool |
| `make_splits.py` | filtered pool → DB-level train/dev/final_eval |
| `build_hard_eval.py` | dev split → 英文困难 mini-dev |

推荐顺序：

```text
normalize -> relativize -> inspect -> build_task_pool
-> cache_and_filter -> make_splits -> build_hard_eval
```

先按 [`../../../data/raw/README.md`](../../../data/raw/README.md) 下载数据。每个脚本的完整参数可通过 `--help` 查看：

```bash
python sqlite_agent/scripts/data/build_task_pool.py --help
python sqlite_agent/scripts/data/cache_and_filter_task_pool.py --help
python sqlite_agent/scripts/data/make_splits.py --help
```

正式构造口径与规模见 [`../../../docs/数据模块面试学习笔记.md`](../../../docs/数据模块面试学习笔记.md)。
