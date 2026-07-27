#!/bin/bash
# MIT Engaging / SLURM — SCM web extraction for one seed category
#SBATCH --job-name=scm-web
#SBATCH --output=logs/scm-web-%j.out
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../../.." && pwd)}"
cd "$REPO_ROOT"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
export SCM_OUTPUT_ROOT="${SCM_OUTPUT_ROOT:-$OUTPUT_DIR/scm}"
export TAVILY_API_KEY="${TAVILY_API_KEY:?Set TAVILY_API_KEY}"
export OPENAI_API_KEY="${OPENAI_API_KEY:?Set OPENAI_API_KEY}"
export WEB_LIMIT="${WEB_LIMIT:-50}"

SUBCATEGORY="${SUBCATEGORY:?Set SUBCATEGORY}"
LIT="${LIT:-${SCM_OUTPUT_ROOT}/extractions/${SUBCATEGORY}_merged.jsonl}"

python -m pipeline.scm.cluster web \
  --subcategory "$SUBCATEGORY" \
  --literature-results "$LIT" \
  --web-limit "$WEB_LIMIT" \
  --cluster-dir "$SCM_OUTPUT_ROOT"

echo "SCM web extraction complete for $SUBCATEGORY"
echo "Carbon-capture execution: disabled"
