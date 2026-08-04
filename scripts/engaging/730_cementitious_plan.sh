#!/bin/bash
# MIT Engaging — lightweight screening shard plan (no LLM).
# For the full ~5.5GB pickle, prefer submitting 730_cementitious_preprocess_plan.sh
# with --mem=64G rather than running this on a login node.
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"

: "${PICKLE_PATH:=${PAPER_RECORDS_PATH:-}}"
: "${PICKLE_PATH:?Set PICKLE_PATH or PAPER_RECORDS_PATH to the absolute corpus pickle path}"
: "${RESULTS_ROOT:?Set RESULTS_ROOT to the results root directory}"

export PICKLE_PATH
export RESULTS_ROOT
export PAPER_RECORDS_PATH="${PAPER_RECORDS_PATH:-$PICKLE_PATH}"
SHARD_SIZE="${SHARD_SIZE:-10000}"
export CEMENTITIOUS_WORKERS="${CEMENTITIOUS_WORKERS:-1}"

# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
source "$_SCRIPT_DIR/_resolve_cementitious_out.sh"
resolve_cementitious_out || exit 1
# shellcheck source=scripts/engaging/_cementitious_slurm_diagnostics.sh
source "$_SCRIPT_DIR/_cementitious_slurm_diagnostics.sh"
cementitious_log_diagnostics "plan-screen"

echo "REPO_ROOT=$REPO_ROOT"
echo "PICKLE_PATH=$PICKLE_PATH"
echo "RESULTS_ROOT=$RESULTS_ROOT"
echo "OUT=$OUT"
echo "SHARD_SIZE=$SHARD_SIZE"
if [[ ! -f "$PICKLE_PATH" ]]; then
  echo "ERROR: pickle not found: $PICKLE_PATH" >&2
  exit 1
fi
echo "pickle_bytes=$(wc -c < "$PICKLE_PATH" | tr -d ' ')"

mkdir -p "$OUT"
python -m pipeline.cementitious.cluster plan-screen \
  --shard-size "$SHARD_SIZE" \
  --input "$PICKLE_PATH" \
  --output "$OUT"

echo "Screen array range: $(tr -d '\n' < "$OUT/metadata/screen_array_range.txt")"
echo "Corpus shards: $OUT/metadata/corpus_shards_manifest.json"
echo "Plan complete -> $OUT/checkpoints/plan_screen.complete"
