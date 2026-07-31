# SFT 消融构造脚本

本目录保存可复现的 SFT 对照构造器，不属于默认训练链路。

| 脚本 | 研究用途 |
|---|---|
| `build_mixed_sft.py` | 构造早期确定性混合冷启动数据 |
| `build_sft_v2_json.py` | 将旧 XML envelope 监督转换为 canonical JSON |
| `build_sft_v3_augmented.py` | 构造机械轨迹增强消融组 |
| `build_english_formal_sft.py` | 构造仅英文数据对照组 |

查看参数：

```bash
python sqlite_agent/scripts/archive/sft/build_sft_v2_json.py --help
python sqlite_agent/scripts/archive/sft/build_sft_v3_augmented.py --help
```

建议把实验输出写入 `outputs/ablation/`。正式训练集仍是 `data/sft/v3_real_json/sft_v3_real_json_5817.jsonl`，正式入口见 [`../../sft/README.md`](../../sft/README.md)。
