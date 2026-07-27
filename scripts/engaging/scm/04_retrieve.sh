#!/bin/bash
# MIT Engaging / SLURM — retrieve/rank one SCM seed category across corpus shards
#SBATCH --job-name=scm-retrieve
#SBATCH --output=logs/scm-retrieve-%A_%a.out
#SBATCH --array=0-15
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=48G

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../../.." && pwd)}"
cd "$REPO_ROOT"

module load python/3.11 2>/dev/null || true

: "${PICKLE_PATH:?Set PICKLE_PATH to the absolute corpus pickle path}"
export PICKLE_PATH
export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
export SCM_OUTPUT_ROOT="${SCM_OUTPUT_ROOT:-$OUTPUT_DIR/scm}"

SUBCATEGORY="${SUBCATEGORY:?Set SUBCATEGORY e.g. slag_cement}"
SHARD_SIZE="${SHARD_SIZE:-10000}"
TASK_ID="${SLURM_ARRAY_TASK_ID:-0}"
SCREENING="${SCREENING:-${SCM_OUTPUT_ROOT}/screening_merged.jsonl}"
if [[ ! -f "$SCREENING" && -f "${SCM_OUTPUT_ROOT}/screening/screening_merged.jsonl" ]]; then
  SCREENING="${SCM_OUTPUT_ROOT}/screening/screening_merged.jsonl"
fi

python -m pipeline.scm.cluster retrieve \
  --subcategory "$SUBCATEGORY" \
  --task-id "$TASK_ID" \
  --shard-size "$SHARD_SIZE" \
  --screening-results "$SCREENING" \
  --input "$PICKLE_PATH" \
  --cluster-dir "$SCM_OUTPUT_ROOT"

echo "SCM retrieve shard $TASK_ID complete for $SUBCATEGORY"
echo "Carbon-capture execution: disabled"
