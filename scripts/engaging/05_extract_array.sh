#!/bin/bash
# MIT Engaging / SLURM — extract 26-question results for global top-N papers
#SBATCH --job-name=ccs-extract
#SBATCH --output=logs/ccs-extract-%A_%a.out
#SBATCH --array=0-9
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/research_agent}"
cd "$REPO_ROOT"

module load python/3.11 2>/dev/null || true
python -m pip install --user -q -r requirements-screening.txt

export PICKLE_PATH="${PICKLE_PATH:-$HOME/filtered_records_rohan.pkl}"
export OPENAI_API_KEY="${OPENAI_API_KEY:?Set OPENAI_API_KEY}"
export EXTRACTION_CONCURRENCY="${EXTRACTION_CONCURRENCY:-4}"
export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"

METHODOLOGY="${METHODOLOGY:?Set METHODOLOGY e.g. amine_absorption}"
EXTRACT_BATCH_SIZE="${EXTRACT_BATCH_SIZE:-5}"
TASK_ID="${SLURM_ARRAY_TASK_ID:-0}"
RANKED="outputs/carbon_capture/ranked/${METHODOLOGY}_final.jsonl"

python pipeline/run_carbon_capture_cluster.py extract \
  --methodology "$METHODOLOGY" \
  --ranked-results "$RANKED" \
  --task-id "$TASK_ID" \
  --extract-batch-size "$EXTRACT_BATCH_SIZE" \
  --cluster-dir carbon_capture

echo "Extraction batch $TASK_ID complete for $METHODOLOGY"
