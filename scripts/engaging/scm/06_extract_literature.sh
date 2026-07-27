#!/bin/bash
# MIT Engaging / SLURM — literature extraction for one SCM seed category
#SBATCH --job-name=scm-extract-lit
#SBATCH --output=logs/scm-extract-lit-%j.out
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
export EXTRACTION_CONCURRENCY="${EXTRACTION_CONCURRENCY:-4}"

SUBCATEGORY="${SUBCATEGORY:?Set SUBCATEGORY}"
RANKED="${RANKED:-${SCM_OUTPUT_ROOT}/ranked/${SUBCATEGORY}_final.jsonl}"

python -m pipeline.scm.cluster extract \
  --subcategory "$SUBCATEGORY" \
  --ranked-results "$RANKED" \
  --input "$PICKLE_PATH" \
  --cluster-dir "$SCM_OUTPUT_ROOT"

echo "SCM literature extract complete for $SUBCATEGORY"
echo "Carbon-capture execution: disabled"
