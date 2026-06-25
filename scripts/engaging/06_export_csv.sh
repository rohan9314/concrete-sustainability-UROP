#!/bin/bash
# MIT Engaging — merge extractions and export CSV (login node)
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/research_agent}"
cd "$REPO_ROOT"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
METHODOLOGY="${METHODOLOGY:?Set METHODOLOGY e.g. amine_absorption}"

EXTRACT_DIR="${OUTPUT_DIR}/carbon_capture/shards/extract/${METHODOLOGY}"
MERGED="${OUTPUT_DIR}/carbon_capture/extractions/${METHODOLOGY}_merged.jsonl"

python pipeline/run_carbon_capture_cluster.py merge-extract \
  --methodology "$METHODOLOGY" \
  --inputs "$EXTRACT_DIR" \
  --cluster-dir carbon_capture

python pipeline/run_carbon_capture_cluster.py export-csv \
  --methodology "$METHODOLOGY" \
  --extraction-results "$MERGED" \
  --cluster-dir carbon_capture

echo "CSV files -> ${OUTPUT_DIR}/carbon_capture/csv/${METHODOLOGY}_answers.csv"
