# Shared settings for the Explorer Slurm jobs. Sourced by every job script; never run directly.
# Model serving settings come from docs/DECISIONS.md 2026-11-08 and ROADMAP.md "Model serving".
# Every runner's copy must match them exactly; change them only with an approved freeze change.

# Where things live. Scratch is purged monthly with no backup: copy results off after each job.
FINQA_REPO="${FINQA_REPO:-/scratch/$USER/finqa-verify}"   # the git clone (human-managed)
FINQA_ROOT="${FINQA_ROOT:-/scratch/$USER/finqa}"          # envs, model files, caches, logs
VLLM_ENV="$FINQA_ROOT/envs/vllm-0.32.0-cu129"

# Model and server (frozen; docs/DECISIONS.md 2026-11-08).
MODEL="Qwen/Qwen3.8-27B"
MODEL_REVISION="37561816e66b5b9153b1b64c10968c18c1e6f4a0"
VLLM_VERSION="0.32.0"
TORCH_VERSION="2.13.0"
TORCH_BACKEND="cu129"
# PyPI's vllm 0.32.0 is the CUDA 13 build (needs libcudart.so.13); the recorded setup is the
# CUDA 12.9 build from the release page.
VLLM_WHEEL="https://github.com/vllm-project/vllm/releases/download/v${VLLM_VERSION}/vllm-${VLLM_VERSION}+${TORCH_BACKEND}-cp38-abi3-manylinux_2_28_x86_64.whl"
VLLM_PYTHON="3.12"
MAX_MODEL_LEN=32768

export PATH="$HOME/.local/bin:$PATH"
export HF_HOME="$FINQA_ROOT/hf"                    # model files on scratch, not home (75 GB quota)
export UV_CACHE_DIR="$FINQA_ROOT/uv-cache"
export UV_PYTHON_INSTALL_DIR="$FINQA_ROOT/uv-python"

# Compute nodes send traffic through a proxy; the local vLLM server must bypass it.
export no_proxy="127.0.0.1,localhost"
export NO_PROXY="$no_proxy"

log() { echo "[$(date '+%F %T')] $*"; }

job_header() {
    log "job ${SLURM_JOB_ID:-?} (${SLURM_JOB_NAME:-?}) on $(hostname)"
    log "repo $FINQA_REPO at commit $(git -C "$FINQA_REPO" rev-parse --short HEAD 2>/dev/null || echo '?')"
}
