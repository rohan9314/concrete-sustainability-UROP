#!/bin/bash
# Shared RESULTS_ROOT → OUT normalization for Cementitious Materials Engaging scripts.
# Mirrors pipeline.cementitious.paths.resolve_results_dir.
#
# Usage (source from other scripts via REPO_ROOT — never via Slurm spool BASH_SOURCE):
#   source "$REPO_ROOT/scripts/engaging/_resolve_cementitious_out.sh"
#   resolve_cementitious_out   # sets OUT
#
# Rules:
#   - RESULTS_ROOT=/parent           → OUT=/parent/7-30 results
#   - RESULTS_ROOT=/parent/7-30 results → OUT=/parent/7-30 results (no nesting)
#   - Paths containing "730 results" are refused (legacy; do not write)

resolve_cementitious_out() {
  : "${RESULTS_ROOT:?Set RESULTS_ROOT}"
  local root="${RESULTS_ROOT%/}"
  if [[ "$root" == *"730 results"* ]]; then
    echo "ERROR: Stale RESULTS_ROOT points at legacy '730 results': $RESULTS_ROOT" >&2
    echo "ERROR: Use '7-30 results' instead. Legacy dirs are preserved; not written to." >&2
    echo "ERROR: Optional migration: python -m pipeline.cementitious.cluster migrate-legacy-results" >&2
    return 1
  fi
  if [[ "$(basename "$root")" == "7-30 results" ]]; then
    OUT="$root"
  else
    OUT="${root}/7-30 results"
  fi
  # Guard nested duplication
  if [[ "$(basename "$(dirname "$OUT")")" == "7-30 results" && "$(basename "$OUT")" == "7-30 results" ]]; then
    OUT="$(dirname "$OUT")"
  fi
  export OUT
  return 0
}
