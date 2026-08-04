#!/bin/bash
# MIT Engaging — true web-extraction array task (assigned URLs only).
#SBATCH --job-name=cm-web-extract
#SBATCH --output=logs/cm-web-extract-%A_%a.out
#SBATCH --error=logs/cm-web-extract-%A_%a.err
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"
mkdir -p logs

: "${RESULTS_ROOT:?Set RESULTS_ROOT}"
: "${SLURM_ARRAY_TASK_ID:?Must run as a Slurm array task}"

export CEMENTITIOUS_STAGE=web_extract
export CEMENTITIOUS_WORKERS="${CEMENTITIOUS_WORKERS:-1}"
export CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB="${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-${CEMENTITIOUS_SOFT_WEB_EXTRACT_GB:-12.8}}"

# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
source "$_SCRIPT_DIR/_resolve_cementitious_out.sh"
resolve_cementitious_out || exit 1
MANIFEST="${OUT}/metadata/web_extraction_shards.json"
TASK_ID="${SLURM_ARRAY_TASK_ID}"

RESUME_FLAG=()
if [[ "${RESUME:-0}" == "1" ]]; then
  RESUME_FLAG=(--resume)
fi
KEYWORD_FLAG=()
if [[ "${KEYWORD_ONLY:-0}" == "1" ]]; then
  KEYWORD_FLAG=(--keyword-only)
fi

echo "web-extract shard TASK_ID=$TASK_ID OUT=$OUT"
echo "OPENAI_API_KEY: $([ -n "${OPENAI_API_KEY:-}" ] && echo set || echo unset)"
echo "TAVILY_API_KEY: $([ -n "${TAVILY_API_KEY:-}" ] && echo set || echo unset)"

python -m pipeline.cementitious.cluster web-extract \
  --shard-id "$TASK_ID" \
  --manifest "$MANIFEST" \
  --output "$OUT" \
  "${RESUME_FLAG[@]}" \
  "${KEYWORD_FLAG[@]}"
