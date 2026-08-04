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

# Resolve REPO_ROOT without BASH_SOURCE (Slurm may copy this script under /var/spool/slurmd).
_cem_helper=""
for _cem_cand in "${REPO_ROOT:-}" "${SLURM_SUBMIT_DIR:-}"; do
  [[ -n "${_cem_cand}" ]] || continue
  if [[ -f "${_cem_cand%/}/scripts/engaging/_cementitious_repo_root.sh" ]]; then
    _cem_helper="${_cem_cand%/}/scripts/engaging/_cementitious_repo_root.sh"
    break
  fi
done
if [[ -z "${_cem_helper}" ]]; then
  echo "ERROR: could not locate scripts/engaging/_cementitious_repo_root.sh (stage=${CEMENTITIOUS_STAGE:-job})." >&2
  echo "ERROR: Export a validated REPO_ROOT from the launcher; Slurm spool is not the repository." >&2
  echo "ERROR: REPO_ROOT=${REPO_ROOT:-<unset>} SLURM_SUBMIT_DIR=${SLURM_SUBMIT_DIR:-<unset>}" >&2
  exit 1
fi
# shellcheck source=scripts/engaging/_cementitious_repo_root.sh
source "${_cem_helper}"
cementitious_resolve_repo_root "${CEMENTITIOUS_STAGE:-job}" || exit 1
cd "$REPO_ROOT"
mkdir -p logs
unset _cem_helper _cem_cand


: "${RESULTS_ROOT:?Set RESULTS_ROOT}"
: "${SLURM_ARRAY_TASK_ID:?Must run as a Slurm array task}"

export CEMENTITIOUS_STAGE=screen
export CEMENTITIOUS_WORKERS="${CEMENTITIOUS_WORKERS:-1}"
export CEMENTITIOUS_BATCH_SIZE="${CEMENTITIOUS_BATCH_SIZE:-25}"
export CEMENTITIOUS_MAX_IN_FLIGHT="${CEMENTITIOUS_MAX_IN_FLIGHT:-1}"
# Soft ceiling <= 80% of --mem=8G unless calibrated override provided.
export CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB="${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-${CEMENTITIOUS_SOFT_SCREEN_GB:-6.4}}"

# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
cementitious_source_engaging_helper "_resolve_cementitious_out.sh" "${CEMENTITIOUS_STAGE:-job}" || exit 1
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
cementitious_source_engaging_helper "_cementitious_slurm_diagnostics.sh" "${CEMENTITIOUS_STAGE:-job}" || exit 1
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
