#!/bin/bash
# MIT Engaging — true web-extraction array task (assigned URLs only).
#SBATCH --job-name=cm-web-extract
#SBATCH --output=logs/cm-web-extract-%A_%a.out
#SBATCH --error=logs/cm-web-extract-%A_%a.err
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
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

export CEMENTITIOUS_STAGE=web_extract
export CEMENTITIOUS_WORKERS="${CEMENTITIOUS_WORKERS:-1}"
export CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB="${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-${CEMENTITIOUS_SOFT_WEB_EXTRACT_GB:-12.8}}"

# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
cementitious_source_engaging_helper "_resolve_cementitious_out.sh" "${CEMENTITIOUS_STAGE:-job}" || exit 1
resolve_cementitious_out || exit 1
MANIFEST="${OUT}/metadata/web_extraction_shards.json"
TASK_ID="${SLURM_ARRAY_TASK_ID}"

RESUME_FLAG=()
if [[ "${RESUME:-0}" == "1" ]]; then
  RESUME_FLAG=(--resume)
fi
KEYWORD_FLAG=()
if [[ "${KEYWORD_ONLY:-0}" == "1" ]]; then
  KEYWORD_FLAG=(--keyword-only)
fi

echo "web-extract shard TASK_ID=$TASK_ID OUT=$OUT"
echo "OPENAI_API_KEY: $([ -n "${OPENAI_API_KEY:-}" ] && echo set || echo unset)"
echo "TAVILY_API_KEY: $([ -n "${TAVILY_API_KEY:-}" ] && echo set || echo unset)"

python -m pipeline.cementitious.cluster web-extract \
  --shard-id "$TASK_ID" \
  --manifest "$MANIFEST" \
  --output "$OUT" \
  "${RESUME_FLAG[@]}" \
  "${KEYWORD_FLAG[@]}"
