#!/bin/bash
# Submit retrieve array jobs for all six carbon capture methodologies.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/research_agent}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for METHODOLOGY in amine_absorption membrane_separation calcium_looping oxyfuel_combustion cryogenic_capture mineralization; do
  echo "Submitting retrieve array for $METHODOLOGY"
  sbatch --export=ALL,METHODOLOGY="$METHODOLOGY" "$SCRIPT_DIR/03_retrieve_array.sh"
done
