#!/bin/bash
# Sync Engaging "7-30 results" to the local Mac UROP folder.
# Run this on your Mac (not on Engaging).
#
# Required environment variables:
#   ENGAGING_HOST          e.g. user@engaging-login-host
#   ENGAGING_RESULTS_PATH  remote RESULTS_ROOT (parent of "7-30 results")
#   LOCAL_UROP_DIR         local UROP folder (destination parent)
#
# Destination:
#   "${LOCAL_UROP_DIR}/7-30 results"
#
# Examples:
#   export ENGAGING_HOST="<username>@engaging-login-host"
#   export ENGAGING_RESULTS_PATH="/orcd/.../urop_results"
#   export LOCAL_UROP_DIR="$HOME/path/to/UROP"
#   bash scripts/local/sync_730_results.sh --dry-run
#   bash scripts/local/sync_730_results.sh
#   bash scripts/local/sync_730_results.sh --yes
#
set -euo pipefail

YES=0
DRY_RUN=0
DELETE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --delete) DELETE=1; shift ;;
    -h|--help)
      sed -n '1,40p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

: "${ENGAGING_HOST:?Set ENGAGING_HOST (e.g. user@engaging-login-host)}"
: "${ENGAGING_RESULTS_PATH:?Set ENGAGING_RESULTS_PATH to the remote RESULTS_ROOT}"
: "${LOCAL_UROP_DIR:?Set LOCAL_UROP_DIR to your local UROP folder}"

if [[ ! -d "$LOCAL_UROP_DIR" ]]; then
  echo "ERROR: LOCAL_UROP_DIR does not exist: $LOCAL_UROP_DIR" >&2
  exit 1
fi

SRC="${ENGAGING_HOST}:${ENGAGING_RESULTS_PATH}/7-30 results/"
DEST="${LOCAL_UROP_DIR}/7-30 results/"

mkdir -p "$DEST"

echo "Source:      $SRC"
echo "Destination: $DEST"
if [[ "$DELETE" -eq 1 ]]; then
  echo "Mode:        rsync with --delete (destructive for local extras)"
else
  echo "Mode:        rsync without --delete (local extras preserved)"
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Dry-run:     yes"
fi

if [[ "$YES" -ne 1 ]]; then
  read -r -p "Proceed with sync? [y/N] " answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 1 ;;
  esac
fi

RSYNC_ARGS=(-avh --progress)
if [[ "$DRY_RUN" -eq 1 ]]; then
  RSYNC_ARGS+=(--dry-run)
fi
if [[ "$DELETE" -eq 1 ]]; then
  RSYNC_ARGS+=(--delete)
fi

LOG_FILE="${LOCAL_UROP_DIR}/7-30 results/sync.log"
mkdir -p "${LOCAL_UROP_DIR}/7-30 results"

{
  echo "==== sync $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
  echo "SRC=$SRC"
  echo "DEST=$DEST"
  echo "DRY_RUN=$DRY_RUN DELETE=$DELETE"
  rsync "${RSYNC_ARGS[@]}" "$SRC" "$DEST"
  echo "==== done ===="
} | tee -a "$LOG_FILE"

echo "Sync log: $LOG_FILE"
