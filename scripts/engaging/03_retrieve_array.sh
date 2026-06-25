#!/bin/bash
# MIT Engaging / SLURM — retrieve/rank one methodology across corpus shards
# Submit once per methodology, or set METHODOLOGY in the environment.
#SBATCH --job-name=ccs-retrieve
#SBATCH --output=logs/ccs-retrieve-%A_%a.out
#SBATCH --array=0-15
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=24G

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/research_agent}"
cd "$REPO_ROOT"

module load python/3.11 2>/dev/null || true
python -m pip install --user -q -r requirements-screening.txt

export PICKLE_PATH="${PICKLE_PATH:-$HOME/filtered_records_rohan.pkl}"
export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"

METHODOLOGY="${METHODOLOGY:?Set METHODOLOGY e.g. amine_absorption}"
SHARD_SIZE="${SHARD_SIZE:-10000}"
TASK_ID="${SLURM_ARRAY_TASK_ID:-0}"
SCREENING="${SCREENING:-outputs/carbon_capture/screening_merged.jsonl}"

python pipeline/run_carbon_capture_cluster.py retrieve \
  --methodology "$METHODOLOGY" \
  --task-id "$TASK_ID" \
  --shard-size "$SHARD_SIZE" \
  --screening-results "$SCREENING" \
  --cluster-dir carbon_capture

echo "Retrieve shard $TASK_ID complete for $METHODOLOGY"
