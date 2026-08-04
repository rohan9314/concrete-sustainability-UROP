#!/bin/bash
# MIT Engaging / SLURM — export SCM seed-category CSVs
#SBATCH --job-name=scm-export
#SBATCH --output=logs/scm-export-%j.out
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../../.." && pwd)}"
cd "$REPO_ROOT"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
export SCM_OUTPUT_ROOT="${SCM_OUTPUT_ROOT:-$OUTPUT_DIR/scm}"
SUBCATEGORY="${SUBCATEGORY:?Set SUBCATEGORY}"
LIT="${LIT:-${SCM_OUTPUT_ROOT}/extractions/${SUBCATEGORY}_merged.jsonl}"
WEB="${WEB:-${SCM_OUTPUT_ROOT}/web/${SUBCATEGORY}_web.jsonl}"

python -m pipeline.scm.cluster export-csv \
  --subcategory "$SUBCATEGORY" \
  --extraction-results "$LIT" \
  --web-results "$WEB" \
  --cluster-dir "$SCM_OUTPUT_ROOT"

echo "SCM export-csv complete for $SUBCATEGORY"
echo "Carbon-capture execution: disabled"
