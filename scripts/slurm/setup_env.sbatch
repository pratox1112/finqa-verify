#!/bin/bash
# Builds the two environments on scratch: the vLLM server env (pinned versions) and the
# project env (uv sync from uv.lock), and fetches the FinanceBench sample. CPU only.
#
# Submit from the repo root, with your course account:
#   mkdir -p /scratch/$USER/finqa/logs
#   sbatch --account=<course-account> scripts/slurm/setup_env.sbatch
#SBATCH --job-name=finqa-setup
#SBATCH --partition=short
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=/scratch/%u/finqa/logs/%x-%j.out
set -euo pipefail
source "$SLURM_SUBMIT_DIR/scripts/slurm/common.sh"
job_header

mkdir -p "$FINQA_ROOT/envs" "$HF_HOME"

if [[ ! -x "$VLLM_ENV/bin/python" ]]; then
    log "creating vLLM env at $VLLM_ENV"
    uv venv --python "$VLLM_PYTHON" "$VLLM_ENV"
fi
log "installing vllm==$VLLM_VERSION, torch==$TORCH_VERSION ($TORCH_BACKEND)"
VIRTUAL_ENV="$VLLM_ENV" uv pip install --python "$VLLM_ENV/bin/python" \
    --torch-backend "$TORCH_BACKEND" "vllm==$VLLM_VERSION" "torch==$TORCH_VERSION"

# Fail loudly if the installed versions are not the recorded ones.
"$VLLM_ENV/bin/python" - "$VLLM_VERSION" "$TORCH_VERSION" "$TORCH_BACKEND" <<'PY'
import sys
import torch
import vllm

want_vllm, want_torch, backend = sys.argv[1:]
print(f"vllm {vllm.__version__}, torch {torch.__version__}, CUDA {torch.version.cuda}")
cuda = backend.removeprefix("cu")
ok = (
    vllm.__version__.split("+")[0] == want_vllm
    and torch.__version__ == f"{want_torch}+{backend}"
    and (torch.version.cuda or "").replace(".", "") == cuda
)
sys.exit(0 if ok else "installed versions differ from docs/DECISIONS.md 2026-11-08")
PY

log "project env: uv sync --frozen in $FINQA_REPO"
cd "$FINQA_REPO"
uv sync --frozen
uv run --frozen python -c "from finqa.ingestion import financebench; print(financebench.download())"

log "done"
