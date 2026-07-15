#!/bin/bash
# MIT Engaging — merge literature extraction shards (login node)
# Run AFTER extract array jobs complete, BEFORE web extraction.
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
METHODOLOGY="${METHODOLOGY:?Set METHODOLOGY e.g. amine_absorption}"

EXTRACT_DIR="${OUTPUT_DIR}/carbon_capture/shards/extract/${METHODOLOGY}"

python pipeline/run_carbon_capture_cluster.py merge-extract \
  --methodology "$METHODOLOGY" \
  --inputs "$EXTRACT_DIR" \
  --cluster-dir carbon_capture

echo "Merged literature -> ${OUTPUT_DIR}/carbon_capture/extractions/${METHODOLOGY}_merged.jsonl"
