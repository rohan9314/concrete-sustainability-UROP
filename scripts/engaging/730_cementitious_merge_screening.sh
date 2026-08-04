#!/bin/bash
# MIT Engaging — verify + merge all screening shards.
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"

: "${RESULTS_ROOT:?Set RESULTS_ROOT}"
# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
source "$_SCRIPT_DIR/_resolve_cementitious_out.sh"
resolve_cementitious_out || exit 1

python -m pipeline.cementitious.cluster merge-screen --output "$OUT"
echo "screen merge complete -> $OUT/checkpoints/screen_merge.complete"
