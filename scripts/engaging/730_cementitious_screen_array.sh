#!/bin/bash
# MIT Engaging — true screening array task (one corpus JSONL shard only).
# Does NOT load the full pickle. Prefer --mem (total process budget) for pilots.
#SBATCH --job-name=cm-screen
#SBATCH --output=logs/cm-screen-%A_%a.out
#SBATCH --error=logs/cm-screen-%A_%a.err
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
# Default array concurrency is applied at submit time (e.g. --array=0-N%1).
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"
mkdir -p logs

: "${RESULTS_ROOT:?Set RESULTS_ROOT}"
: "${SLURM_ARRAY_TASK_ID:?Must run as a Slurm array task}"

export CEMENTITIOUS_STAGE=screen
export CEMENTITIOUS_WORKERS="${CEMENTITIOUS_WORKERS:-1}"
export CEMENTITIOUS_BATCH_SIZE="${CEMENTITIOUS_BATCH_SIZE:-25}"
export CEMENTITIOUS_MAX_IN_FLIGHT="${CEMENTITIOUS_MAX_IN_FLIGHT:-1}"
# Soft ceiling <= 80% of --mem=8G unless calibrated override provided.
export CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB="${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-${CEMENTITIOUS_SOFT_SCREEN_GB:-6.4}}"

# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
source "$_SCRIPT_DIR/_resolve_cementitious_out.sh"
resolve_cementitious_out || exit 1
MANIFEST="${OUT}/metadata/screen_shards.json"
TASK_ID="${SLURM_ARRAY_TASK_ID}"

SHARD_PATH=""
if [[ -f "$MANIFEST" ]]; then
  SHARD_PATH="$(python - <<PY
import json
from pathlib import Path
manifest = json.loads(Path(r"""$MANIFEST""").read_text())
shards = manifest["shards"] if isinstance(manifest, dict) else manifest
entry = next(s for s in shards if int(s["shard_id"]) == int("$TASK_ID"))
print(entry.get("record_shard_path") or "")
PY
)"
fi

# shellcheck source=scripts/engaging/_cementitious_slurm_diagnostics.sh
source "$_SCRIPT_DIR/_cementitious_slurm_diagnostics.sh"
cementitious_log_diagnostics "screen" "$SHARD_PATH"

RESUME_FLAG=()
if [[ "${RESUME:-0}" == "1" ]]; then
  RESUME_FLAG=(--resume)
fi
KEYWORD_FLAG=()
if [[ "${KEYWORD_ONLY:-0}" == "1" ]]; then
  KEYWORD_FLAG=(--keyword-only)
fi

python -m pipeline.cementitious.cluster screen \
  --shard-id "$TASK_ID" \
  --manifest "$MANIFEST" \
  --output "$OUT" \
  "${RESUME_FLAG[@]}" \
  "${KEYWORD_FLAG[@]}"
