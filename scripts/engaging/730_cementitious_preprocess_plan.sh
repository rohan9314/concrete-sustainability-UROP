#!/bin/bash
# MIT Engaging — one-time corpus preprocess + screen plan (full pickle load once).
# Isolates the expensive deserialize to a single high-memory job (not an array).
#SBATCH --job-name=cm-preprocess
#SBATCH --output=logs/cm-preprocess-%j.out
#SBATCH --error=logs/cm-preprocess-%j.err
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=64G
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


: "${PICKLE_PATH:=${PAPER_RECORDS_PATH:-}}"
: "${PICKLE_PATH:?Set PICKLE_PATH or PAPER_RECORDS_PATH to the absolute corpus pickle path}"
: "${RESULTS_ROOT:?Set RESULTS_ROOT to the results root directory}"

export PICKLE_PATH
export RESULTS_ROOT
export PAPER_RECORDS_PATH="${PAPER_RECORDS_PATH:-$PICKLE_PATH}"
export SHARD_SIZE="${SHARD_SIZE:-10000}"
export CEMENTITIOUS_WORKERS="${CEMENTITIOUS_WORKERS:-1}"
export CEMENTITIOUS_BATCH_SIZE="${CEMENTITIOUS_BATCH_SIZE:-25}"
export CEMENTITIOUS_STAGE=preprocess_plan
export CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB="${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-${CEMENTITIOUS_SOFT_PREPROCESS_GB:-51.2}}"

# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
cementitious_source_engaging_helper "_resolve_cementitious_out.sh" "${CEMENTITIOUS_STAGE:-job}" || exit 1
resolve_cementitious_out || exit 1
# shellcheck source=scripts/engaging/_cementitious_slurm_diagnostics.sh
cementitious_source_engaging_helper "_cementitious_slurm_diagnostics.sh" "${CEMENTITIOUS_STAGE:-job}" || exit 1
cementitious_log_diagnostics "preprocess-plan"

if [[ ! -f "$PICKLE_PATH" ]]; then
  echo "ERROR: pickle not found: $PICKLE_PATH" >&2
  exit 1
fi
echo "pickle_bytes=$(wc -c < "$PICKLE_PATH" | tr -d ' ')"

python -m pipeline.cementitious.cluster plan-screen \
  --shard-size "$SHARD_SIZE" \
  --input "$PICKLE_PATH" \
  --output "$OUT"

echo "Screen array range: $(tr -d '\n' < "$OUT/metadata/screen_array_range.txt")"
echo "Corpus shards: $OUT/metadata/corpus_shards_manifest.json"
echo "Plan complete -> $OUT/checkpoints/plan_screen.complete"
