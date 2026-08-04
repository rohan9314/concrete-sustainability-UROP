#!/bin/bash
# MIT Engaging — full pipeline wrapper (delegates to sharded one-command launcher).
set -euo pipefail
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$_SCRIPT_DIR/run_730_results.sh"
