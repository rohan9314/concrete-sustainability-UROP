#!/bin/bash
# MIT Engaging — merge screening shards (run once on login node)
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/research_agent}"
cd "$REPO_ROOT"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"

python pipeline/run_carbon_capture_cluster.py merge-screen \
  --cluster-dir carbon_capture \
  --inputs "${OUTPUT_DIR}/carbon_capture/shards/screening"

echo "Merged screening -> ${OUTPUT_DIR}/carbon_capture/screening_merged.jsonl"
