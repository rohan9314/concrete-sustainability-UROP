#!/bin/bash
# MIT Engaging — true extraction array task (one ranked-candidate shard only).
#SBATCH --job-name=cm-extract
#SBATCH --output=logs/cm-extract-%A_%a.out
#SBATCH --error=logs/cm-extract-%A_%a.err
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"
mkdir -p logs

: "${RESULTS_ROOT:?Set RESULTS_ROOT}"
: "${OPENAI_API_KEY:?OPENAI_API_KEY is required for extraction}"
: "${SLURM_ARRAY_TASK_ID:?Must run as a Slurm array task}"

export CEMENTITIOUS_STAGE=extract
export CEMENTITIOUS_WORKERS="${CEMENTITIOUS_WORKERS:-1}"
export CEMENTITIOUS_BATCH_SIZE="${CEMENTITIOUS_BATCH_SIZE:-25}"
export CEMENTITIOUS_MAX_IN_FLIGHT="${CEMENTITIOUS_MAX_IN_FLIGHT:-1}"
export CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB="${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-${CEMENTITIOUS_SOFT_EXTRACT_GB:-6.4}}"

# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
source "$_SCRIPT_DIR/_resolve_cementitious_out.sh"
resolve_cementitious_out || exit 1
MANIFEST="${OUT}/metadata/extraction_shards.json"
TASK_ID="${SLURM_ARRAY_TASK_ID}"

# shellcheck source=scripts/engaging/_cementitious_slurm_diagnostics.sh
source "$_SCRIPT_DIR/_cementitious_slurm_diagnostics.sh"
cementitious_log_diagnostics "extract"

RESUME_FLAG=()
if [[ "${RESUME:-0}" == "1" ]]; then
  RESUME_FLAG=(--resume)
fi
KEYWORD_FLAG=()
if [[ "${KEYWORD_ONLY:-0}" == "1" ]]; then
  KEYWORD_FLAG=(--keyword-only)
fi

python -m pipeline.cementitious.cluster extract \
  --shard-id "$TASK_ID" \
  --manifest "$MANIFEST" \
  --output "$OUT" \
  "${RESUME_FLAG[@]}" \
  "${KEYWORD_FLAG[@]}"
