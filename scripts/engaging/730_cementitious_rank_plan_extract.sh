#!/bin/bash
# MIT Engaging — rank candidates and plan extraction shards (no LLM extraction).
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"

: "${RESULTS_ROOT:?Set RESULTS_ROOT}"
# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
source "$_SCRIPT_DIR/_resolve_cementitious_out.sh"
resolve_cementitious_out || exit 1
EXTRACT_SHARD_SIZE="${EXTRACT_SHARD_SIZE:-25}"
TOP_N="${TOP_N:-${TOP_N_SOURCES:-50}}"

python -m pipeline.cementitious.cluster rank-and-plan-extraction \
  --output "$OUT" \
  --top-n "$TOP_N" \
  --extract-shard-size "$EXTRACT_SHARD_SIZE"

echo "Extract array range: $(tr -d '\n' < "$OUT/metadata/extract_array_range.txt")"
echo "rank-and-plan-extraction complete -> $OUT/checkpoints/rank_plan_extract.complete"
