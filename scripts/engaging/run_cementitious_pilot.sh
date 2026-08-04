#!/bin/bash
# Convenience alias for the memory-safe Engaging pilot (literature + Tavily web).
set -euo pipefail
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$_SCRIPT_DIR/run_cementitious_full_workflow.sh" --pilot "$@"
