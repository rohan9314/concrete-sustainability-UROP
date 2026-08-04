#!/bin/bash
# MIT Engaging — deterministic web query planning (no Tavily/LLM). Safe on login node.
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

echo "REPO_ROOT=$REPO_ROOT"
echo "RESULTS_ROOT=$RESULTS_ROOT"
echo "OUT=$OUT"
echo "SELECTED_SUBCATEGORIES=${SELECTED_SUBCATEGORIES:-<all>}"
echo "SELECTED_SUB_SUBCATEGORIES=${SELECTED_SUB_SUBCATEGORIES:-<all>}"
echo "WEB_QUERIES_PER_SUBCATEGORY=${WEB_QUERIES_PER_SUBCATEGORY:-3}"
echo "WEB_QUERIES_PER_SUB_SUBCATEGORY=${WEB_QUERIES_PER_SUB_SUBCATEGORY:-5}"
echo "WEB_RESULTS_PER_QUERY=${WEB_RESULTS_PER_QUERY:-10}"
echo "WEB_MAX_URLS_PER_BRANCH=${WEB_MAX_URLS_PER_BRANCH:-50}"
echo "WEB_MAX_TOTAL_URLS=${WEB_MAX_TOTAL_URLS:-1000}"
echo "WEB_SEARCH_SHARD_SIZE=${WEB_SEARCH_SHARD_SIZE:-10}"
echo "TAVILY_API_KEY: $([ -n "${TAVILY_API_KEY:-}" ] && echo set || echo unset)"

mkdir -p "$OUT"
python -m pipeline.cementitious.cluster plan-web-queries --output "$OUT"

echo "Web search array range: $(tr -d '\n' < "$OUT/metadata/web_search_array_range.txt" || true)"
echo "Plan complete -> $OUT/checkpoints/plan_web_queries.complete"
