#!/bin/bash
# MIT Engaging — final taxonomy partition export (after dedupe/QC).
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
# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
cementitious_source_engaging_helper "_resolve_cementitious_out.sh" "${CEMENTITIOUS_STAGE:-job}" || exit 1
resolve_cementitious_out || exit 1
MERGED="${OUT}/metadata/merged_records.csv"

if [[ ! -f "$MERGED" ]]; then
  echo "ERROR: missing merged records at $MERGED" >&2
  exit 1
fi

FORCE_FLAG=()
if [[ "${FORCE:-0}" == "1" ]]; then
  FORCE_FLAG=(--force)
fi

python -m pipeline.cementitious.cluster export \
  --output "$OUT" \
  "${FORCE_FLAG[@]}"

echo "Export complete -> $OUT"
echo "User-facing master: $OUT/cementitious_materials_results/cementitious_materials_all_records.csv"
echo "Internal/compat master: $OUT/all_records/cementitious_materials_all_records.csv"
