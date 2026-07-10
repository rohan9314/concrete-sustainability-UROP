#!/bin/bash
# Submit web extraction jobs for all six carbon capture methodologies.
# Requires merge-extract outputs to exist for each methodology.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/concrete_sustainability_urop}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for METHODOLOGY in amine_absorption membrane_separation calcium_looping oxyfuel_combustion cryogenic_capture mineralization; do
  echo "Submitting web extraction for $METHODOLOGY"
  sbatch --export=ALL,METHODOLOGY="$METHODOLOGY" "$SCRIPT_DIR/07_web_extract.sh"
done
