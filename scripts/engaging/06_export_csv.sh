#!/bin/bash
# Compatibility wrapper: prefer 06_merge_extract.sh then 08_export_csv.sh
# (web stage 07 should run between them).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "NOTE: 06_export_csv.sh now only merges literature. Use 08_export_csv.sh after web." >&2
bash "$SCRIPT_DIR/06_merge_extract.sh"
