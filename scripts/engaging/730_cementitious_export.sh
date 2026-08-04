#!/bin/bash
# MIT Engaging — final taxonomy partition export (after dedupe/QC).
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"

: "${RESULTS_ROOT:?Set RESULTS_ROOT}"
# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
source "$_SCRIPT_DIR/_resolve_cementitious_out.sh"
resolve_cementitious_out || exit 1
MERGED="${OUT}/metadata/merged_records.csv"

if [[ ! -f "$MERGED" ]]; then
  echo "ERROR: missing merged records at $MERGED" >&2
  exit 1
fi

FORCE_FLAG=()
if [[ "${FORCE:-0}" == "1" ]]; then
  FORCE_FLAG=(--force)
fi

python -m pipeline.cementitious.cluster export \
  --output "$OUT" \
  "${FORCE_FLAG[@]}"

echo "Export complete -> $OUT"
echo "All records: $OUT/all_records/cementitious_materials_all_records.csv"
