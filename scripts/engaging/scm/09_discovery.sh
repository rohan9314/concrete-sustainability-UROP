#!/bin/bash
# MIT Engaging / SLURM — SCM open discovery (independent of seed categories)
#SBATCH --job-name=scm-discovery
#SBATCH --output=logs/scm-discovery-%j.out
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../../.." && pwd)}"
cd "$REPO_ROOT"

: "${PICKLE_PATH:?Set PICKLE_PATH}"
export PICKLE_PATH
export OPENAI_API_KEY="${OPENAI_API_KEY:?Set OPENAI_API_KEY}"
export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
export SCM_OUTPUT_ROOT="${SCM_OUTPUT_ROOT:-$OUTPUT_DIR/scm}"
export TOP_N_SOURCES="${TOP_N_SOURCES:-50}"
export WEB_LIMIT="${WEB_LIMIT:-50}"

SCREENING="${SCREENING:-${SCM_OUTPUT_ROOT}/screening_merged.jsonl}"
if [[ ! -f "$SCREENING" && -f "${SCM_OUTPUT_ROOT}/screening/screening_merged.jsonl" ]]; then
  SCREENING="${SCM_OUTPUT_ROOT}/screening/screening_merged.jsonl"
fi

python -m pipeline.scm run-discovery \
  --input "$PICKLE_PATH" \
  --out-dir "$SCM_OUTPUT_ROOT" \
  --screening-results "$SCREENING" \
  --top-n "$TOP_N_SOURCES" \
  --web-limit "$WEB_LIMIT"

echo "SCM discovery complete -> ${SCM_OUTPUT_ROOT}/discovery/"
echo "Carbon-capture execution: disabled"
