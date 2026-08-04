#!/bin/bash
# MIT Engaging — true web-search array task (assigned query IDs only; Tavily).
#SBATCH --job-name=cm-web-search
#SBATCH --output=logs/cm-web-search-%A_%a.out
#SBATCH --error=logs/cm-web-search-%A_%a.err
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"
mkdir -p logs

: "${RESULTS_ROOT:?Set RESULTS_ROOT}"
: "${SLURM_ARRAY_TASK_ID:?Must run as a Slurm array task}"
: "${TAVILY_API_KEY:?TAVILY_API_KEY required for web-search}"

export CEMENTITIOUS_STAGE=web_search
export CEMENTITIOUS_WORKERS="${CEMENTITIOUS_WORKERS:-1}"
export CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB="${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-${CEMENTITIOUS_SOFT_WEB_SEARCH_GB:-6.4}}"

# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
source "$_SCRIPT_DIR/_resolve_cementitious_out.sh"
resolve_cementitious_out || exit 1
MANIFEST="${OUT}/metadata/web_query_shards.json"
TASK_ID="${SLURM_ARRAY_TASK_ID}"

RESUME_FLAG=()
if [[ "${RESUME:-0}" == "1" ]]; then
  RESUME_FLAG=(--resume)
fi

echo "web-search shard TASK_ID=$TASK_ID OUT=$OUT"
echo "TAVILY_API_KEY: set"

python -m pipeline.cementitious.cluster web-search \
  --shard-id "$TASK_ID" \
  --manifest "$MANIFEST" \
  --output "$OUT" \
  "${RESUME_FLAG[@]}"
