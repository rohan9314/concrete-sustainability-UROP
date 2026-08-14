#!/bin/bash
# Convenience alias for the cheap single-branch Engaging smoke test (--pilot / --smoke).
# For production-like full-taxonomy pilots use:
#   bash scripts/engaging/run_concrete_decarbonization_full_workflow.sh --pilot-50
#   bash scripts/engaging/run_concrete_decarbonization_full_workflow.sh --pilot-1000
# Full production:
#   bash scripts/engaging/run_concrete_decarbonization_full_workflow.sh --full
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
exec bash "$REPO_ROOT/scripts/engaging/run_concrete_decarbonization_full_workflow.sh" --pilot "$@"
