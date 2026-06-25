#!/bin/bash
# MIT Engaging — merge extractions and export CSV (login node)
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/research_agent}"
cd "$REPO_ROOT"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
METHODOLOGY="${METHODOLOGY:?Set METHODOLOGY e.g. amine_absorption}"

python pipeline/run_carbon_capture_cluster.py merge-extract \
  --methodology "$METHODOLOGY" \
  --inputs "outputs/carbon_capture/shards/extract/${METHODOLOGY}" \
  --cluster-dir carbon_capture

python pipeline/run_carbon_capture_cluster.py export-csv \
  --methodology "$METHODOLOGY" \
  --extraction-results "outputs/carbon_capture/extractions/${METHODOLOGY}_merged.jsonl" \
  --cluster-dir carbon_capture

echo "CSV files -> outputs/carbon_capture/csv/${METHODOLOGY}_answers.csv"
