#!/bin/bash
# Downloads the model at the pinned revision into $HF_HOME on scratch (about 55 GB). CPU only.
# Needs the vLLM env from setup_env.sbatch (it provides the `hf` command).
#
# Submit from the repo root:
#   sbatch --account=<course-account> scripts/slurm/download_model.sbatch
# or right after setup:  --dependency=afterok:<setup job id>
#SBATCH --job-name=finqa-download
#SBATCH --partition=short
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=06:00:00
#SBATCH --output=/scratch/%u/finqa/logs/%x-%j.out
set -euo pipefail
source "$SLURM_SUBMIT_DIR/scripts/slurm/common.sh"
job_header

log "downloading $MODEL at revision $MODEL_REVISION into $HF_HOME"
"$VLLM_ENV/bin/hf" download "$MODEL" --revision "$MODEL_REVISION"

snapshot="$HF_HOME/hub/models--${MODEL//\//--}/snapshots/$MODEL_REVISION"
if [[ ! -f "$snapshot/config.json" ]]; then
    log "ERROR: no config.json in $snapshot"
    exit 1
fi
log "snapshot $snapshot: $(du -shL "$snapshot" | cut -f1), $(ls "$snapshot" | wc -l) files"
log "done"
