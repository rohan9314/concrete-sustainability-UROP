#!/bin/bash
# EXAMPLE ONLY — not wired to the live website.
# Example pattern for running corpus shards with parallel batch workers.
#
# Each worker processes one index range of the pickle corpus.
# Run multiple workers locally or in a distributed batch-processing environment.

set -euo pipefail

# Assign each worker a unique ID (0, 1, 2, ...) when running in parallel.
WORKER_ID=${WORKER_ID:-0}
BATCH_SIZE=10000
START=$((WORKER_ID * BATCH_SIZE))
END=$((START + BATCH_SIZE))

cd "$(dirname "$0")/.."

# Load environment (example)
# source .venv/bin/activate
# export $(grep -v '^#' backend/.env | xargs)

export EXTRACTION_CONCURRENCY="${EXTRACTION_CONCURRENCY:-4}"
export TOP_N_SOURCES="${TOP_N_SOURCES:-50}"

python pipeline/run_batch.py \
  --start "$START" \
  --end "$END" \
  --out "outputs/batch_${START}_${END}.jsonl" \
  --query "cement concrete decarbonization"

# Optional: run extraction on ranked papers in each shard
# python pipeline/run_batch.py \
#   --start "$START" \
#   --end "$END" \
#   --extract \
#   --technology "carbon capture" \
#   --out "outputs/batch_${START}_${END}.jsonl"

echo "Shard complete: ${START}-${END}"
