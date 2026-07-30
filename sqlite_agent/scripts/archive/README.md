# 历史脚本

该目录保存已被替代的数据构造器，用于实验追溯和消融研究。

- `sft/build_mixed_sft.py`：确定性的 V1 冷启动混合数据
- `sft/build_sft_v2_json.py`：一次性的 XML 到 JSON 迁移
- `sft/build_sft_v3_augmented.py`：机械式 V3 数据增强实验
- `sft/build_english_formal_sft.py`：仅英文正式训练集构造实验

这些脚本可能依赖历史输入和兼容解析器，不是当前 SFT 或 RL 流水线入口。
