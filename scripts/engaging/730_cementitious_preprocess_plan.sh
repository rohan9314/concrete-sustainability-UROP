#!/bin/bash
# MIT Engaging — one-time corpus preprocess + screen plan (full pickle load once).
# Isolates the expensive deserialize to a single high-memory job (not an array).
#SBATCH --job-name=cm-preprocess
#SBATCH --output=logs/cm-preprocess-%j.out
#SBATCH --error=logs/cm-preprocess-%j.err
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=64G
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"
mkdir -p logs

: "${PICKLE_PATH:=${PAPER_RECORDS_PATH:-}}"
: "${PICKLE_PATH:?Set PICKLE_PATH or PAPER_RECORDS_PATH to the absolute corpus pickle path}"
: "${RESULTS_ROOT:?Set RESULTS_ROOT to the results root directory}"

export PICKLE_PATH
export RESULTS_ROOT
export PAPER_RECORDS_PATH="${PAPER_RECORDS_PATH:-$PICKLE_PATH}"
export SHARD_SIZE="${SHARD_SIZE:-10000}"
export CEMENTITIOUS_WORKERS="${CEMENTITIOUS_WORKERS:-1}"
export CEMENTITIOUS_BATCH_SIZE="${CEMENTITIOUS_BATCH_SIZE:-25}"
export CEMENTITIOUS_STAGE=preprocess_plan
export CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB="${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-${CEMENTITIOUS_SOFT_PREPROCESS_GB:-51.2}}"

# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
source "$_SCRIPT_DIR/_resolve_cementitious_out.sh"
resolve_cementitious_out || exit 1
# shellcheck source=scripts/engaging/_cementitious_slurm_diagnostics.sh
source "$_SCRIPT_DIR/_cementitious_slurm_diagnostics.sh"
cementitious_log_diagnostics "preprocess-plan"

if [[ ! -f "$PICKLE_PATH" ]]; then
  echo "ERROR: pickle not found: $PICKLE_PATH" >&2
  exit 1
fi
echo "pickle_bytes=$(wc -c < "$PICKLE_PATH" | tr -d ' ')"

python -m pipeline.cementitious.cluster plan-screen \
  --shard-size "$SHARD_SIZE" \
  --input "$PICKLE_PATH" \
  --output "$OUT"

echo "Screen array range: $(tr -d '\n' < "$OUT/metadata/screen_array_range.txt")"
echo "Corpus shards: $OUT/metadata/corpus_shards_manifest.json"
echo "Plan complete -> $OUT/checkpoints/plan_screen.complete"
