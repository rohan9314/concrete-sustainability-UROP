#!/bin/bash
# MIT Engaging / SLURM — merge SCM literature/web evidence (SCM only)
#SBATCH --job-name=scm-merge-evidence
#SBATCH --output=logs/scm-merge-evidence-%j.out
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../../.." && pwd)}"
cd "$REPO_ROOT"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
export SCM_OUTPUT_ROOT="${SCM_OUTPUT_ROOT:-$OUTPUT_DIR/scm}"

python -m pipeline.scm merge-evidence --out-dir "$SCM_OUTPUT_ROOT"

echo "SCM merge-evidence complete -> ${SCM_OUTPUT_ROOT}/merged/"
echo "Carbon-capture execution: disabled"
