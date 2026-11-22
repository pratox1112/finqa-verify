#!/bin/bash
# Starts the vLLM server on one A100 80 GB, waits until it answers, runs the given command
# from the repo against it, then stops the server. The server lives only inside this job.
#
# Submit from the repo root; everything after the script name is the command to run:
#   sbatch --account=<course-account> scripts/slurm/serve_and_run.sbatch \
#       uv run --frozen finqa draft --config configs/baselines/s0_closed_book.yaml --split dev
# With no command it only checks that the server starts and answers.
#SBATCH --job-name=finqa-vllm
#SBATCH --partition=gpu
#SBATCH --gres=gpu:a100:1
#SBATCH --constraint=a100@80g
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=/scratch/%u/finqa/logs/%x-%j.out
set -euo pipefail
source "$SLURM_SUBMIT_DIR/scripts/slurm/common.sh"
job_header
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

PORT=$((8000 + ${SLURM_JOB_ID:-0} % 1000))   # avoid clashing with other jobs on the node
SERVER_LOG="$FINQA_ROOT/logs/vllm-${SLURM_JOB_ID:-local}.log"

log "starting vLLM on port $PORT (server log: $SERVER_LOG)"
# For the server only: the env's bin on PATH (FlashInfer compiles its sampling kernel at
# startup and needs the env's `ninja`), and offline mode, so it uses only the downloaded
# snapshot. The command run below may still download (e.g. the embedding model, once).
PATH="$VLLM_ENV/bin:$PATH" HF_HUB_OFFLINE=1 "$VLLM_ENV/bin/vllm" serve "$MODEL" \
    --revision "$MODEL_REVISION" --tokenizer-revision "$MODEL_REVISION" \
    --dtype bfloat16 --max-model-len "$MAX_MODEL_LEN" \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder \
    --host 127.0.0.1 --port "$PORT" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
trap 'log "stopping vLLM"; kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 180); do                     # up to 30 minutes to load the weights
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        log "ERROR: vLLM exited during startup; last lines of $SERVER_LOG:"
        tail -n 40 "$SERVER_LOG"
        exit 1
    fi
    if curl -sf --noproxy '*' "http://127.0.0.1:$PORT/v1/models" >/dev/null; then
        break
    fi
    sleep 10
done
curl -sf --noproxy '*' "http://127.0.0.1:$PORT/v1/models" || { log "ERROR: server not ready"; exit 1; }
echo
log "server ready"

export VLLM_BASE_URL="http://127.0.0.1:$PORT/v1"
if [[ $# -gt 0 ]]; then
    cd "$FINQA_REPO"
    log "running: $*"
    "$@"
fi
log "done"
