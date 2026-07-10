#!/bin/bash
# MIT Engaging / SLURM — internet search + web extraction for one methodology
# Run AFTER merge-extract so company/project seeds from literature are available.
#SBATCH --job-name=ccs-web
#SBATCH --output=logs/ccs-web-%j.out
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/concrete_sustainability_urop}"
cd "$REPO_ROOT"

module load python/3.11 2>/dev/null || true
python -m pip install --user -q -r requirements-screening.txt

export PICKLE_PATH="${PICKLE_PATH:-$HOME/filtered_records_rohan.pkl}"
export OPENAI_API_KEY="${OPENAI_API_KEY:?Set OPENAI_API_KEY}"
export TAVILY_API_KEY="${TAVILY_API_KEY:?Set TAVILY_API_KEY}"
export EXTRACTION_CONCURRENCY="${EXTRACTION_CONCURRENCY:-4}"
export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
export WEB_LIMIT="${WEB_LIMIT:-50}"

METHODOLOGY="${METHODOLOGY:?Set METHODOLOGY e.g. amine_absorption}"
LITERATURE="${OUTPUT_DIR}/carbon_capture/extractions/${METHODOLOGY}_merged.jsonl"

if [[ ! -f "$LITERATURE" ]]; then
  echo "ERROR: Literature merge not found: $LITERATURE" >&2
  echo "Run: METHODOLOGY=$METHODOLOGY bash scripts/engaging/06_merge_extract.sh" >&2
  exit 1
fi

python pipeline/run_carbon_capture_cluster.py web \
  --methodology "$METHODOLOGY" \
  --literature-results "$LITERATURE" \
  --web-limit "$WEB_LIMIT" \
  --cluster-dir carbon_capture

echo "Web extraction complete for $METHODOLOGY -> ${OUTPUT_DIR}/carbon_capture/web/${METHODOLOGY}_web.jsonl"
