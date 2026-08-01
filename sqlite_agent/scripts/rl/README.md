# RL 与 Slime 运行指南

本目录覆盖 RL prompt 构造、SFT 模型检查与合并、Hugging Face→Megatron 转换、Slime 数据准备和 GRPO 启动。

## 完整运行顺序

```text
安装并检查 Slime 环境
→ build_rl_smoke_tasks.py
→ run_rl_dryrun_hf.py
→ merge_lora_checkpoint.py
→ Slime convert_hf_to_torch_dist.py
→ prepare_slime_data.py（启动器也会自动执行）
→ run_slime_rl_smoke.sh
→ 检查 metrics / logs / checkpoint
```

## 1. 安装基础项目环境

本地 dry-run 不需要 Slime：

```bash
cd SQLite-Agentic-RL
python -m pip install -e '.[sft,data,dev]'
export PYTHONPATH="$PWD/sqlite_agent:${PYTHONPATH:-}"
```

验证：

```bash
python -c 'import torch, transformers, peft; print(torch.__version__)'
pytest -q tests/test_reward.py tests/test_json_protocol.py
```

## 2. 安装 Slime、Ray、SGLang 与 Megatron

Slime 会联动 Megatron 与 SGLang，并可能包含针对两者的兼容补丁。官方建议优先使用预装依赖的 Docker 镜像，避免手工组合不兼容版本：

- [Slime 官方 Quick Start](https://github.com/THUDM/slime/blob/main/docs/en/get_started/quick_start.md)
- [Slime 官方 Usage Guide](https://github.com/THUDM/slime/blob/main/docs/en/get_started/usage.md)
- [Slime GitHub](https://github.com/THUDM/slime)

### 推荐：官方 Docker

```bash
docker pull slimerl/slime:latest

docker run --rm --gpus all \
  --ipc=host \
  --shm-size=16g \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  -v /host/path/SQLite-Agentic-RL:/workspace/SQLite-Agentic-RL \
  -v /host/path/models:/models \
  -it slimerl/slime:latest /bin/bash
```

把两个 `/host/path/...` 替换为宿主机上的项目和模型目录。进入容器后：

```bash
export PROJECT_ROOT=/workspace/SQLite-Agentic-RL
export SLIME_ROOT=/root/slime
export MEGATRON_ROOT=/root/Megatron-LM

cd "$PROJECT_ROOT"
python -m pip install -e '.[sft,data,dev]'
export PYTHONPATH="$MEGATRON_ROOT:$PROJECT_ROOT/sqlite_agent:${PYTHONPATH:-}"
```

官方镜像版本会更新，路径也可能调整。先检查真实安装位置：

```bash
test -f "$SLIME_ROOT/train.py"
test -d "$MEGATRON_ROOT/megatron"
test -f "$SLIME_ROOT/scripts/models/qwen2.5-3B.sh"

python -c 'import ray, sglang, torch; print("ray", ray.__version__); print("sglang", sglang.__version__); print("torch", torch.__version__)'
cd "$SLIME_ROOT" && git rev-parse HEAD
```

如果镜像内目录不同，应修改 `SLIME_ROOT` 与 `MEGATRON_ROOT`，不要复制一份新的 Megatron 到未知路径。

### 备选：源码/Conda 环境

Slime 官方提供 `build_conda.sh`，但这种方式更容易遇到 CUDA、Transformer Engine、Flash Attention、SGLang 与 Megatron 版本冲突。请严格跟随当前 Slime Quick Start，不要在项目通用 Python 环境里单独 `pip install ray sglang megatron` 后假设可以兼容。

本仓库目前没有锁定 Slime/Megatron/SGLang 的完整 commit 组合。严格复现实验时应记录 Docker image digest、Slime commit、Megatron commit、CUDA、PyTorch 和 GPU 型号；`latest` 适合搭建当前环境，不代表与历史训练逐字节一致。

还应确认当前 Slime checkout 支持启动器使用的自定义 hook：

```bash
cd "$SLIME_ROOT"
python train.py --help | grep -E 'custom-generate-function-path|custom-rm-path|custom-rollout-log-function-path'
```

如果这些参数不存在，说明 Slime 上游接口已经变化，需要切换到兼容 revision 或适配启动脚本，不能直接忽略参数错误。

## 3. 构造 RL 任务

### 轻量 smoke/repro 数据

仓库已经发布 768 条训练任务和 60 条验证任务。需要重建时：

```bash
python sqlite_agent/scripts/rl/build_rl_smoke_tasks.py \
  --train-source data/splits/v2_db_seed42/train.jsonl \
  --val-source data/eval/mini_dev.jsonl \
  --output-dir data/rl \
  --train-limit 768 \
  --val-limit 60 \
  --seed 768 \
  --medium-ratio 0.55 \
  --hard-ratio 0.35 \
  --simple-ratio 0.10 \
  --max-empty-ratio 0.12
```

### 正式 Stage 2 数据

```bash
python sqlite_agent/scripts/rl/build_rl_smoke_tasks.py \
  --train-source data/splits/v2_db_seed42/train.jsonl \
  --val-source data/splits/v2_db_seed42/dev.jsonl \
  --output-dir data/rl/formal_stage2_2048 \
  --train-limit 2048 \
  --val-limit 120 \
  --seed 708 \
  --medium-ratio 0.45 \
  --hard-ratio 0.45 \
  --simple-ratio 0.10 \
  --max-empty-ratio 0.08
```

输出均为 `train_tasks.jsonl`、`val_tasks.jsonl` 和 `manifest.json`。768/60 只用于链路验证；正式结果使用 2,048/120，不要混写两套统计。

## 4. 在更新权重前运行 HF dry-run

dry-run 使用 SFT adapter 真实生成多轮轨迹，但不做梯度更新，用来检查 parser、工具、reward 和同组奖励方差：

```bash
BASE_MODEL=/models/Qwen2.5-Coder-3B-Instruct
ADAPTER=/workspace/checkpoints/qwen25_coder3b_sqlite_sft/checkpoint-600

cd "$PROJECT_ROOT"
python sqlite_agent/scripts/rl/run_rl_dryrun_hf.py \
  --base-model "$BASE_MODEL" \
  --adapter "$ADAPTER" \
  --tasks data/rl/train_tasks.jsonl \
  --output outputs/rl/dryrun_rollouts.jsonl \
  --summary-output outputs/rl/dryrun_summary.json \
  --limit 100 \
  --group-size 4 \
  --max-tool-steps 8 \
  --temperature 0.7 \
  --top-p 0.95 \
  --include-traces \
  --local-files-only
```

检查 summary 中是否有 `group_reward_variance_rate`，以及 protocol、executable、equivalent、parse failed 和 budget exceeded 是否合理。若同一 prompt 的四条轨迹奖励完全相同，GRPO 几乎没有组内学习信号。

## 5. 合并 SFT LoRA 为 Hugging Face 模型

SGLang rollout 需要完整 HF checkpoint，不能只加载 LoRA adapter：

```bash
MERGED_HF=/models/qwen25-coder3b-sqlite-sft-merged-hf

python sqlite_agent/scripts/rl/merge_lora_checkpoint.py \
  --base-model "$BASE_MODEL" \
  --adapter "$ADAPTER" \
  --output "$MERGED_HF" \
  --local-files-only
```

验证：

```bash
test -f "$MERGED_HF/config.json"
test -f "$MERGED_HF/model.safetensors" || find "$MERGED_HF" -maxdepth 1 -name '*.safetensors' -print
```

## 6. 转换为 Megatron `torch_dist` checkpoint

Slime 的 SGLang rollout 读取 HF checkpoint，Megatron actor/reference 则读取 Megatron checkpoint。官方推荐 `torch_dist` 格式，因为它支持不同并行配置之间的自动分片。

```bash
export MEGATRON_CKPT=/models/qwen25-coder3b-sqlite-sft-torch-dist

cd "$SLIME_ROOT"
source scripts/models/qwen2.5-3B.sh

PYTHONPATH="$MEGATRON_ROOT" python tools/convert_hf_to_torch_dist.py \
  "${MODEL_ARGS[@]}" \
  --hf-checkpoint "$MERGED_HF" \
  --save "$MEGATRON_CKPT"
```

验证时应传 checkpoint 根目录，而不是 `iter_xxx/` 子目录：

```bash
test -f "$MEGATRON_CKPT/latest_checkpointed_iteration.txt"
find "$MEGATRON_CKPT" -name '*.distcp' -print -quit
```

模型配置必须与 Qwen2.5-Coder-3B 一致。如果当前 Slime 没有 `qwen2.5-3B.sh`，不要直接借用其他 Qwen 配置，应根据该 revision 的官方模型配置补齐参数。

## 7. 转换 Slime prompt 数据

启动器会自动执行这一步；单独运行适合在训练前检查格式：

```bash
cd "$PROJECT_ROOT"

python sqlite_agent/scripts/rl/prepare_slime_data.py \
  --tasks data/rl/formal_stage2_2048/train_tasks.jsonl \
  --output-jsonl outputs/rl/formal_stage2_2048/slime/train.jsonl \
  --output-parquet outputs/rl/formal_stage2_2048/slime/train.parquet

python sqlite_agent/scripts/rl/prepare_slime_data.py \
  --tasks data/rl/formal_stage2_2048/val_tasks.jsonl \
  --output-jsonl outputs/rl/formal_stage2_2048/slime/val.jsonl \
  --output-parquet outputs/rl/formal_stage2_2048/slime/val.parquet
```

Gold SQL/Result 只进入 metadata/reward label，不会渲染进模型 prompt。

## 8. 启动正式 4 卡 Slime GRPO

> `run_slime_rl_smoke.sh` 会执行 `ray stop --force`，并终止当前节点上的 Ray/SGLang 进程。只应在独占训练容器或专用节点中运行，不要在共享 Ray 集群直接执行。

```bash
cd "$PROJECT_ROOT"

NUM_GPUS=4 \
ACTOR_GPUS=2 \
ROLLOUT_GPUS=2 \
TRAIN_TP_SIZE=2 \
SLIME_ROOT="$SLIME_ROOT" \
MEGATRON_ROOT="$MEGATRON_ROOT" \
MERGED_HF="$MERGED_HF" \
MEGATRON_CKPT="$MEGATRON_CKPT" \
LOAD_CKPT="$MEGATRON_CKPT" \
TRAIN_TASKS="$PROJECT_ROOT/data/rl/formal_stage2_2048/train_tasks.jsonl" \
VAL_TASKS="$PROJECT_ROOT/data/rl/formal_stage2_2048/val_tasks.jsonl" \
WORK_DIR="$PROJECT_ROOT/outputs/rl/formal_stage2_2048/slime" \
OUTPUT_DIR="$PROJECT_ROOT/checkpoints/slime_rl_stage2" \
NUM_ROLLOUT=512 \
ROLLOUT_BATCH_SIZE=4 \
N_SAMPLES_PER_PROMPT=4 \
EVAL_INTERVAL=50 \
SAVE_INTERVAL=511 \
MAX_TOOL_STEPS=6 \
ROLLOUT_MAX_RESPONSE_LEN=512 \
EVAL_MAX_RESPONSE_LEN=512 \
LR=5e-7 \
KL_LOSS_COEF=0.002 \
MAX_TOKENS_PER_GPU=3072 \
OPTIMIZER_CPU_OFFLOAD=1 \
WANDB_PROJECT=sqlite-agentic-rl-v2 \
bash sqlite_agent/scripts/rl/run_slime_rl_smoke.sh
```

启动器会：

1. 把任务转换为 Slime JSONL/Parquet；
2. 检查 HF 与 Megatron checkpoint；
3. 启动 Ray head；
4. 通过 `ray job submit` 启动 Slime；
5. 加载自定义 SQLite Agent、reward 与 metrics hook；
6. 将控制台日志写入 `logs/rl/`。

## 9. 检查输出与续训

```text
outputs/rl/...                 Slime 输入与中间运行文件
logs/rl/*.log                 完整训练日志
logs/rl/*.metrics.jsonl       rollout/eval 聚合指标
checkpoints/slime_rl_stage2/  Megatron actor checkpoint
```

```bash
tail -f logs/rl/*.log
tail -f logs/rl/*.metrics.jsonl
test -f checkpoints/slime_rl_stage2/latest_checkpointed_iteration.txt
```

续训时把 `LOAD_CKPT` 指向已有 actor checkpoint 根目录；`MEGATRON_CKPT` 仍作为 reference checkpoint。不要把 `LOAD_CKPT` 指向 `iter_xxx/` 子目录。

常见问题：

- `latest_checkpointed_iteration.txt` 不存在：传入的不是 Megatron checkpoint 根目录；
- Ray job 找不到 `sqlite_agent_pkg`：检查 runtime env 中的 `PYTHONPATH`；
- SGLang OOM：降低 `SGLANG_MEM_FRACTION_STATIC`、response length 或 token budget；
- Megatron logprob/entropy OOM：单独降低 rollout batch 未必有效，应检查 actor/rollout GPU 隔离、TP、activation recompute 和 optimizer offload；
- 自定义 hook 参数不存在：Slime 版本与本项目启动脚本不兼容。

奖励公式、GRPO 和 reward hacking 分析见 [`../../../docs/面试笔记/RL模块.md`](../../../docs/面试笔记/RL模块.md)。
