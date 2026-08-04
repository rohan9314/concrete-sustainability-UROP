#!/bin/bash
# MIT Engaging — SCM shard plan (login node). Does not submit jobs.
# Uses environment-driven paths only. Never touches carbon-capture outputs.
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../../.." && pwd)}"
cd "$REPO_ROOT"

: "${PICKLE_PATH:?Set PICKLE_PATH to the absolute corpus pickle path}"
export PICKLE_PATH
export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
export SCM_OUTPUT_ROOT="${SCM_OUTPUT_ROOT:-$OUTPUT_DIR/scm}"
SHARD_SIZE="${SHARD_SIZE:-10000}"

python -m pipeline.scm.cluster plan \
  --shard-size "$SHARD_SIZE" \
  --input "$PICKLE_PATH" \
  --cluster-dir "$SCM_OUTPUT_ROOT"

echo "SCM plan complete. Output root: $SCM_OUTPUT_ROOT"
echo "Carbon-capture execution: disabled"
