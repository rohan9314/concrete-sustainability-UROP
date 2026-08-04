#!/bin/bash
# MIT Engaging — dedupe + QC (once, after extraction merge).
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"

: "${RESULTS_ROOT:?Set RESULTS_ROOT}"
# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
source "$_SCRIPT_DIR/_resolve_cementitious_out.sh"
resolve_cementitious_out || exit 1

SKIP=()
if [[ "${SKIP_QC:-0}" == "1" ]]; then
  SKIP=(--skip-qc)
fi
KEYWORD_FLAG=()
if [[ "${KEYWORD_ONLY:-0}" == "1" ]]; then
  KEYWORD_FLAG=(--keyword-only)
fi

python -m pipeline.cementitious.cluster dedupe-qc \
  --output "$OUT" \
  "${SKIP[@]}" \
  "${KEYWORD_FLAG[@]}"

echo "dedupe/qc complete -> $OUT/checkpoints/dedupe_qc.complete"
