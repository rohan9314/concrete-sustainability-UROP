#!/bin/bash
# Repository-root wrapper for the one-command Engaging Cementitious Materials run.
# Usage: ./run_730_results.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$ROOT/scripts/engaging/run_730_results.sh" "$@"
