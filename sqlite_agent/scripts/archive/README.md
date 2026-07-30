# 复现实验与消融脚本

该目录提供不属于默认训练链路的数据构造方案，用于复现实验、协议对照和
消融研究。

| 脚本 | 用途 |
|---|---|
| `sft/build_mixed_sft.py` | 构造确定性的冷启动混合数据 |
| `sft/build_sft_v2_json.py` | 将 XML 格式监督数据转换为 canonical JSON 协议数据 |
| `sft/build_sft_v3_augmented.py` | 构造机械轨迹增强消融组 |
| `sft/build_english_formal_sft.py` | 构造仅英文训练集对照组 |

## 使用方式

先查看目标脚本的参数和默认输出：

```bash
python sqlite_agent/scripts/archive/sft/build_mixed_sft.py --help
python sqlite_agent/scripts/archive/sft/build_sft_v2_json.py --help
python sqlite_agent/scripts/archive/sft/build_sft_v3_augmented.py --help
python sqlite_agent/scripts/archive/sft/build_english_formal_sft.py --help
```

建议把输出写入 `outputs/ablation/`，避免与
`data/sft/v3_real_json/sft_v3_real_json_5817.jsonl` 混用。正式训练入口
见 [`../sft/README.md`](../sft/README.md)。
