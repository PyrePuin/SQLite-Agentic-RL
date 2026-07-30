#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd -- "${SCRIPT_DIR}/../../.." && pwd)}"
SLIME_ROOT="${SLIME_ROOT:-}"
MEGATRON_ROOT="${MEGATRON_ROOT:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RAY_BIN="${RAY_BIN:-ray}"

MERGED_HF="${MERGED_HF:-}"
MEGATRON_CKPT="${MEGATRON_CKPT:-}"
OUTPUT_DIR="${OUTPUT_DIR:-${PROJECT_ROOT}/checkpoints/slime_rl_smoke_ckpt600}"
LOAD_CKPT="${LOAD_CKPT:-${MEGATRON_CKPT}}"

TRAIN_TASKS="${TRAIN_TASKS:-${PROJECT_ROOT}/data/rl/train_tasks.jsonl}"
VAL_TASKS="${VAL_TASKS:-${PROJECT_ROOT}/data/rl/val_tasks.jsonl}"
WORK_DIR="${WORK_DIR:-${PROJECT_ROOT}/outputs/rl/slime_smoke}"
LOG_DIR="${LOG_DIR:-${PROJECT_ROOT}/logs/rl}"
WANDB_PROJECT="${WANDB_PROJECT:-sqlite-agentic-rl-v2}"
WANDB_RUN_NAME="${WANDB_RUN_NAME:-slime_rl_smoke_ckpt600_$(date +%Y%m%d_%H%M%S)}"

NUM_ROLLOUT="${NUM_ROLLOUT:-6}"
ROLLOUT_BATCH_SIZE="${ROLLOUT_BATCH_SIZE:-4}"
N_SAMPLES_PER_PROMPT="${N_SAMPLES_PER_PROMPT:-4}"
NUM_STEPS_PER_ROLLOUT="${NUM_STEPS_PER_ROLLOUT:-1}"
MAX_TOOL_STEPS="${MAX_TOOL_STEPS:-8}"
ROLLOUT_TEMPERATURE="${ROLLOUT_TEMPERATURE:-0.7}"
ROLLOUT_MAX_RESPONSE_LEN="${ROLLOUT_MAX_RESPONSE_LEN:-768}"
EVAL_MAX_RESPONSE_LEN="${EVAL_MAX_RESPONSE_LEN:-768}"
LR="${LR:-5e-7}"
MIN_LR="${MIN_LR:-0.0}"
LR_DECAY_STYLE="${LR_DECAY_STYLE:-constant}"
LR_WARMUP_FRACTION="${LR_WARMUP_FRACTION:-0.0}"
KL_LOSS_COEF="${KL_LOSS_COEF:-0.001}"
KL_LOSS_TYPE="${KL_LOSS_TYPE:-low_var_kl}"
ENTROPY_COEF="${ENTROPY_COEF:-0.0}"
SAVE_INTERVAL="${SAVE_INTERVAL:-3}"
EVAL_INTERVAL="${EVAL_INTERVAL:-1}"
TRAIN_TP_SIZE="${TRAIN_TP_SIZE:-1}"
MAX_TOKENS_PER_GPU="${MAX_TOKENS_PER_GPU:-3072}"
SGLANG_MEM_FRACTION_STATIC="${SGLANG_MEM_FRACTION_STATIC:-0.55}"
OPTIMIZER_CPU_OFFLOAD="${OPTIMIZER_CPU_OFFLOAD:-1}"
OPTIMIZER_OFFLOAD_FRACTION="${OPTIMIZER_OFFLOAD_FRACTION:-1.0}"

for required_name in SLIME_ROOT MEGATRON_ROOT MERGED_HF MEGATRON_CKPT; do
  if [[ -z "${!required_name}" ]]; then
    echo "[rl-smoke] Set ${required_name} to the corresponding local path."
    exit 2
  fi
done

cd "${PROJECT_ROOT}"
mkdir -p "${WORK_DIR}" "${LOG_DIR}" "${OUTPUT_DIR}"
export PYTHONPATH="${PROJECT_ROOT}/sqlite_agent:${PYTHONPATH:-}"
export SQLITE_RL_MAX_TOOL_STEPS="${MAX_TOOL_STEPS}"
export SQLITE_RL_METRICS_JSONL="${LOG_DIR}/${WANDB_RUN_NAME}.metrics.jsonl"
export WANDB_PROJECT WANDB_RUN_NAME

"${PYTHON_BIN}" sqlite_agent/scripts/rl/prepare_slime_data.py \
  --tasks "${TRAIN_TASKS}" \
  --output-jsonl "${WORK_DIR}/train.jsonl" \
  --output-parquet "${WORK_DIR}/train.parquet"
"${PYTHON_BIN}" sqlite_agent/scripts/rl/prepare_slime_data.py \
  --tasks "${VAL_TASKS}" \
  --output-jsonl "${WORK_DIR}/val.jsonl" \
  --output-parquet "${WORK_DIR}/val.parquet"

if [[ ! -d "${MERGED_HF}" ]]; then
  echo "[rl-smoke] MERGED_HF not found: ${MERGED_HF}"
  echo "[rl-smoke] Merge LoRA checkpoint-600 into HF first, then convert to Megatron if the remote Slime setup requires it."
  exit 10
fi
if [[ ! -f "${LOAD_CKPT}/latest_checkpointed_iteration.txt" ]]; then
  echo "[rl-smoke] LOAD_CKPT is not a Megatron checkpoint: ${LOAD_CKPT}"
  echo "[rl-smoke] Convert ${MERGED_HF} to Slime/Megatron format before launching."
  exit 11
fi

"${RAY_BIN}" stop --force || true
pkill -9 -f sglang || true
pkill -9 -f ray || true
sleep 3

LOG_FILE="${LOG_DIR}/${WANDB_RUN_NAME}.log"
cd "${SLIME_ROOT}"
source scripts/models/qwen2.5-3B.sh

export MASTER_ADDR="${MASTER_ADDR:-127.0.0.1}"
"${RAY_BIN}" start --head --node-ip-address "${MASTER_ADDR}" --num-gpus "${NUM_GPUS:-1}" --disable-usage-stats

RUNTIME_ENV_JSON="{\"env_vars\":{\"PYTHONPATH\":\"${MEGATRON_ROOT}:${PROJECT_ROOT}/sqlite_agent\",\"PATH\":\"$(dirname "${PYTHON_BIN}"):${PATH}\",\"SQLITE_RL_MAX_TOOL_STEPS\":\"${MAX_TOOL_STEPS}\",\"SQLITE_RL_METRICS_JSONL\":\"${SQLITE_RL_METRICS_JSONL}\",\"CUDA_DEVICE_MAX_CONNECTIONS\":\"1\"}}"

set -x
"${RAY_BIN}" job submit --address="http://127.0.0.1:8265" \
  --runtime-env-json="${RUNTIME_ENV_JSON}" \
  -- "${PYTHON_BIN}" train.py \
  --actor-num-nodes 1 \
  --actor-num-gpus-per-node "${ACTOR_GPUS:-1}" \
  --rollout-num-gpus "${ROLLOUT_GPUS:-1}" \
  "${MODEL_ARGS[@]}" \
  --hf-checkpoint "${MERGED_HF}" \
  --ref-load "${MEGATRON_CKPT}" \
  --load "${LOAD_CKPT}" \
  --save "${OUTPUT_DIR}" \
  --save-interval "${SAVE_INTERVAL}" \
  --prompt-data "${WORK_DIR}/train.parquet" \
  --input-key prompt \
  --label-key reward_model \
  --metadata-key metadata \
  --rollout-shuffle \
  --num-rollout "${NUM_ROLLOUT}" \
  --rollout-batch-size "${ROLLOUT_BATCH_SIZE}" \
  --n-samples-per-prompt "${N_SAMPLES_PER_PROMPT}" \
  --num-steps-per-rollout "${NUM_STEPS_PER_ROLLOUT}" \
  --global-batch-size "$((ROLLOUT_BATCH_SIZE * N_SAMPLES_PER_PROMPT))" \
  --rollout-max-response-len "${ROLLOUT_MAX_RESPONSE_LEN}" \
  --rollout-temperature "${ROLLOUT_TEMPERATURE}" \
  --eval-interval "${EVAL_INTERVAL}" \
  --eval-prompt-data sqlite_val "${WORK_DIR}/val.parquet" \
  --eval-input-key prompt \
  --eval-label-key reward_model \
  --n-samples-per-eval-prompt 1 \
  --eval-max-response-len "${EVAL_MAX_RESPONSE_LEN}" \
  --tensor-model-parallel-size "${TRAIN_TP_SIZE}" \
  --sequence-parallel \
  --pipeline-model-parallel-size 1 \
  --recompute-granularity full \
  --recompute-method uniform \
  --recompute-num-layers 1 \
  --use-dynamic-batch-size \
  --max-tokens-per-gpu "${MAX_TOKENS_PER_GPU}" \
  --advantage-estimator grpo \
  --use-kl-loss \
  --kl-loss-coef "${KL_LOSS_COEF}" \
  --kl-loss-type "${KL_LOSS_TYPE}" \
  --entropy-coef "${ENTROPY_COEF}" \
  --eps-clip 0.2 \
  --eps-clip-high 0.28 \
  --optimizer adam \
  --lr "${LR}" \
  --min-lr "${MIN_LR}" \
  --lr-decay-style "${LR_DECAY_STYLE}" \
  --lr-warmup-fraction "${LR_WARMUP_FRACTION}" \
  --weight-decay 0.01 \
  --adam-beta1 0.9 \
  --adam-beta2 0.95 \
  $([[ "${OPTIMIZER_CPU_OFFLOAD}" == "1" ]] && printf '%s\n' \
    --optimizer-cpu-offload \
    --optimizer-offload-fraction "${OPTIMIZER_OFFLOAD_FRACTION}" \
    --use-precision-aware-optimizer \
    --overlap-cpu-optimizer-d2h-h2d) \
  --use-wandb \
  --wandb-project "${WANDB_PROJECT}" \
  --wandb-group sqlite-v2-rl \
  --rollout-num-gpus-per-engine 1 \
  --sglang-mem-fraction-static "${SGLANG_MEM_FRACTION_STATIC}" \
  --sglang-disable-cuda-graph \
  --sglang-disable-piecewise-cuda-graph \
  --attention-dropout 0.0 \
  --hidden-dropout 0.0 \
  --no-gradient-accumulation-fusion \
  --accumulate-allreduce-grads-in-fp32 \
  --attention-softmax-in-fp32 \
  --attention-backend flash \
  --custom-generate-function-path sqlite_agent_pkg.rl.slime_agent.generate \
  --custom-rm-path sqlite_agent_pkg.rl.slime_agent.reward_func \
  --custom-rollout-log-function-path sqlite_agent_pkg.rl.slime_metrics.log_rollout_data \
  --custom-eval-rollout-log-function-path sqlite_agent_pkg.rl.slime_metrics.log_eval_rollout_data \
  2>&1 | tee "${LOG_FILE}"
