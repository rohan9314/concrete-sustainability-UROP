#!/bin/bash
# MIT Engaging / SLURM — Stage 1 abstract screening array job
#SBATCH --job-name=ccs-screen
#SBATCH --output=logs/ccs-screen-%A_%a.out
#SBATCH --array=0-15
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"

module load python/3.11 2>/dev/null || true
python -m pip install --user -q -r requirements-screening.txt

: "${PICKLE_PATH:?Set PICKLE_PATH to the absolute corpus pickle path (not assumed inside the repo)}"
export PICKLE_PATH
export OPENAI_API_KEY="${OPENAI_API_KEY:?Set OPENAI_API_KEY}"
export EXTRACTION_CONCURRENCY="${EXTRACTION_CONCURRENCY:-4}"
export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"

SHARD_SIZE="${SHARD_SIZE:-10000}"
TASK_ID="${SLURM_ARRAY_TASK_ID:-0}"

echo "Using PICKLE_PATH=$PICKLE_PATH"
python pipeline/run_carbon_capture_cluster.py screen \
  --task-id "$TASK_ID" \
  --shard-size "$SHARD_SIZE" \
  --input "$PICKLE_PATH" \
  --cluster-dir carbon_capture

echo "Screening shard $TASK_ID complete"
