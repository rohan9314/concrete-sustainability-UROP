#!/bin/bash
# MIT Engaging — merge screening shards (run once on login node)
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"

python pipeline/run_carbon_capture_cluster.py merge-screen \
  --cluster-dir carbon_capture \
  --inputs "${OUTPUT_DIR}/carbon_capture/shards/screening"

echo "Merged screening -> ${OUTPUT_DIR}/carbon_capture/screening_merged.jsonl"
