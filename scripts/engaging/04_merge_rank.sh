#!/bin/bash
# MIT Engaging — merge ranked shards and select global top-N (login node)
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/research_agent}"
cd "$REPO_ROOT"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
export TOP_N_SOURCES="${TOP_N_SOURCES:-50}"

METHODOLOGY="${METHODOLOGY:?Set METHODOLOGY e.g. amine_absorption}"

python pipeline/run_carbon_capture_cluster.py merge-rank \
  --methodology "$METHODOLOGY" \
  --inputs "outputs/carbon_capture/shards/retrieve/${METHODOLOGY}" \
  --top-n "$TOP_N_SOURCES" \
  --cluster-dir carbon_capture

echo "Global ranked list -> outputs/carbon_capture/ranked/${METHODOLOGY}_final.jsonl"
