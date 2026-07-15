#!/bin/bash
# Submit retrieve array jobs for all six carbon capture methodologies.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
: "${PICKLE_PATH:?Set PICKLE_PATH to the absolute corpus pickle path}"

for METHODOLOGY in amine_absorption membrane_separation calcium_looping oxyfuel_combustion cryogenic_capture mineralization; do
  echo "Submitting retrieve array for $METHODOLOGY"
  sbatch --export=ALL,METHODOLOGY="$METHODOLOGY",REPO_ROOT="$REPO_ROOT",OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}",PICKLE_PATH="$PICKLE_PATH" \
    "$SCRIPT_DIR/03_retrieve_array.sh"
done
