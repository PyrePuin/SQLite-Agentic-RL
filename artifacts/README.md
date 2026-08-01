# 模型产物

本仓库有意不提交模型权重。

最终选择的 SFT 产物是
`qwen25-coder3b-sqlite-sft-v3-checkpoint600` 的 LoRA adapter。本地权重
文件约为 228 MiB（约 239 MB），应通过独立的模型托管或网盘分发。

发布 adapter 前应记录：

- 基座模型：`Qwen/Qwen2.5-Coder-3B-Instruct`
- adapter 格式：PEFT LoRA
- 选中的优化器步数：600
- `adapter_model.safetensors` 的 SHA-256
- 下载地址

正式 Slime/Megatron RL checkpoint 约为 41 GiB，因此不包含在仓库中。
可复现配置和验证曲线见
[`docs/技术设计/RL与奖励设计.md`](../docs/技术设计/RL与奖励设计.md) 与
[`results/rl/stage2.validation.jsonl`](../results/rl/stage2.validation.jsonl)。
