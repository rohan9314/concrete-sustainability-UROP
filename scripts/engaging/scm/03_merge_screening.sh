#!/bin/bash
# MIT Engaging / SLURM — merge SCM screening shards
#SBATCH --job-name=scm-merge-screen
#SBATCH --output=logs/scm-merge-screen-%j.out
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../../.." && pwd)}"
cd "$REPO_ROOT"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
export SCM_OUTPUT_ROOT="${SCM_OUTPUT_ROOT:-$OUTPUT_DIR/scm}"
INPUTS="${INPUTS:-${SCM_OUTPUT_ROOT}/shards/screening}"

python -m pipeline.scm.cluster merge-screen \
  --inputs "$INPUTS" \
  --cluster-dir "$SCM_OUTPUT_ROOT"

echo "SCM merge-screening complete -> ${SCM_OUTPUT_ROOT}/screening/screening_merged.jsonl (or screening_merged.jsonl)"
echo "Carbon-capture execution: disabled"
