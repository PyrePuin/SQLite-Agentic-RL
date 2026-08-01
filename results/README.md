# 实验结果

本目录保存可提交、可追踪的结果摘要。它不存放模型权重，也不把私有 W&B 页面当作唯一证据。

| 文件 | 内容 | 来源 |
|---|---|---|
| [`sft/checkpoint600.summary.json`](sft/checkpoint600.summary.json) | SFT checkpoint-600 的 full-dev 聚合指标 | 现有正式文档转录 + W&B run 身份核对 |
| [`rl/stage2.validation.jsonl`](rl/stage2.validation.jsonl) | RL Stage 2 的固定验证曲线 | 现有正式文档转录 + W&B run 身份核对 |

## 证据等级

- `raw_export`：由评测程序或 W&B API 直接导出，可独立重算；
- `documented_metric_transcription`：从已有正式记录转成结构化文件，并关联 run ID，但仓库没有原始 history/rollout；
- `manual_note`：仅供背景参考，不作为正式数值依据。

当前两个文件属于 `documented_metric_transcription`。2026-08-01 核对时，[W&B 项目](https://wandb.ai/puin719703329-ustc/sqlite-agentic-rl-v2)为私有，[正式 SFT run](https://wandb.ai/puin719703329-ustc/sqlite-agentic-rl-v2/runs/4557721e2cd4)和[正式 RL run](https://wandb.ai/puin719703329-ustc/sqlite-agentic-rl-v2/runs/ari4f5ed)状态均为 Finished；RL Overview 的 Summary 为 0 keys，界面只提供 Python API 示例，当前机器也没有 W&B API 凭据，因此没有伪造“原始导出”标记。

严格复现需要补充逐任务 rollout 和原始 summary/history。SFT full-dev 与 RL validation 不是同一任务集合，不能直接相减为 RL 增益。
