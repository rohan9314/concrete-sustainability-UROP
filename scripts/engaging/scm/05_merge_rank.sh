#!/bin/bash
# MIT Engaging / SLURM — merge ranked SCM shards to global top-N
#SBATCH --job-name=scm-merge-rank
#SBATCH --output=logs/scm-merge-rank-%j.out
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../../.." && pwd)}"
cd "$REPO_ROOT"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
export SCM_OUTPUT_ROOT="${SCM_OUTPUT_ROOT:-$OUTPUT_DIR/scm}"
export TOP_N_SOURCES="${TOP_N_SOURCES:-50}"
SUBCATEGORY="${SUBCATEGORY:?Set SUBCATEGORY e.g. slag_cement}"
INPUTS="${INPUTS:-${SCM_OUTPUT_ROOT}/shards/retrieve/${SUBCATEGORY}}"

python -m pipeline.scm.cluster merge-rank \
  --subcategory "$SUBCATEGORY" \
  --inputs "$INPUTS" \
  --top-n "$TOP_N_SOURCES" \
  --cluster-dir "$SCM_OUTPUT_ROOT"

echo "SCM merge-rank complete for $SUBCATEGORY"
echo "Carbon-capture execution: disabled"
