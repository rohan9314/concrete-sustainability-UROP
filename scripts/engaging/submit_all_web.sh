#!/bin/bash
# Submit web extraction jobs for all six carbon capture methodologies.
# Requires merge-extract outputs to exist for each methodology.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

for METHODOLOGY in amine_absorption membrane_separation calcium_looping oxyfuel_combustion cryogenic_capture mineralization; do
  echo "Submitting web extraction for $METHODOLOGY"
  sbatch --export=ALL,METHODOLOGY="$METHODOLOGY",REPO_ROOT="$REPO_ROOT",OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}",OPENAI_API_KEY="${OPENAI_API_KEY:-}",TAVILY_API_KEY="${TAVILY_API_KEY:-}" \
    "$SCRIPT_DIR/07_web_extract.sh"
done
