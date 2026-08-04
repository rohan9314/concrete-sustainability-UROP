#!/bin/bash
# Compatibility wrapper → run_730_results.sh
set -euo pipefail
_LAUNCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${REPO_ROOT:-}" ]] && command -v git >/dev/null 2>&1; then
  if _git_root="$(git -C "$_LAUNCH_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
    REPO_ROOT="$_git_root"
  fi
fi
if [[ -z "${REPO_ROOT:-}" ]]; then
  REPO_ROOT="$(cd "$_LAUNCH_DIR/../.." && pwd)"
fi
export REPO_ROOT
bash "$REPO_ROOT/scripts/engaging/run_730_results.sh"
