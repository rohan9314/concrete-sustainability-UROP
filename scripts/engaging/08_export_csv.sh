#!/bin/bash
# MIT Engaging — export final CSV (literature + web) for one methodology
# Run AFTER merge-extract and web extraction.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/concrete_sustainability_urop}"
cd "$REPO_ROOT"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
METHODOLOGY="${METHODOLOGY:?Set METHODOLOGY e.g. amine_absorption}"

MERGED="${OUTPUT_DIR}/carbon_capture/extractions/${METHODOLOGY}_merged.jsonl"
WEB="${OUTPUT_DIR}/carbon_capture/web/${METHODOLOGY}_web.jsonl"

if [[ ! -f "$MERGED" ]]; then
  echo "ERROR: Literature merge not found: $MERGED" >&2
  echo "Run: METHODOLOGY=$METHODOLOGY bash scripts/engaging/06_merge_extract.sh" >&2
  exit 1
fi

if [[ ! -f "$WEB" ]]; then
  echo "WARNING: Web results not found at $WEB" >&2
  echo "Run: METHODOLOGY=$METHODOLOGY sbatch scripts/engaging/07_web_extract.sh" >&2
  echo "Exporting literature-only CSV for now." >&2
fi

python pipeline/run_carbon_capture_cluster.py export-csv \
  --methodology "$METHODOLOGY" \
  --extraction-results "$MERGED" \
  --web-results "$WEB" \
  --cluster-dir carbon_capture

echo "CSV files -> ${OUTPUT_DIR}/carbon_capture/csv/${METHODOLOGY}_answers.csv"
echo "  (includes literature + web rows when web file is present)"
