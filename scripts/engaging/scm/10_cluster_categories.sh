#!/bin/bash
# MIT Engaging / SLURM — corpus-level SCM category clustering / recommendations
#SBATCH --job-name=scm-cluster
#SBATCH --output=logs/scm-cluster-%j.out
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../../.." && pwd)}"
cd "$REPO_ROOT"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
export SCM_OUTPUT_ROOT="${SCM_OUTPUT_ROOT:-$OUTPUT_DIR/scm}"

# Heuristic-only avoids an LLM call on the login/login-like node unless requested.
HEURISTIC_ONLY="${HEURISTIC_ONLY:-1}"
if [[ "$HEURISTIC_ONLY" == "1" ]]; then
  python -m pipeline.scm cluster-categories --out-dir "$SCM_OUTPUT_ROOT" --heuristic-only
else
  export OPENAI_API_KEY="${OPENAI_API_KEY:?Set OPENAI_API_KEY}"
  python -m pipeline.scm cluster-categories --out-dir "$SCM_OUTPUT_ROOT"
fi

echo "SCM cluster-categories complete -> ${SCM_OUTPUT_ROOT}/discovery/"
echo "Carbon-capture execution: disabled"
