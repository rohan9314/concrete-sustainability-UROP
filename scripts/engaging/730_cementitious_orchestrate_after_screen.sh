#!/bin/bash
# MIT Engaging — post-screen literature orchestration through merge-extract.
# When RUN_MODE is literature-only (or finalize is requested), also submits
# dedupe → optional CCS migrate → export.
# When RUN_MODE is literature-and-web, stops after merge-extract so the launcher
# can join with the web branch.
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
RUN_MODE="${RUN_MODE:-literature-and-web}"
FINALIZE_LITERATURE="${FINALIZE_LITERATURE:-0}"
if [[ "$RUN_MODE" == "literature-only" || "$RUN_MODE" == "literature_only" ]]; then
  FINALIZE_LITERATURE=1
fi

COMMON_EXPORT="${COMMON_EXPORT:-ALL,REPO_ROOT=$REPO_ROOT,RESULTS_ROOT=$RESULTS_ROOT}"
if [[ -n "${PICKLE_PATH:-}" ]]; then
  COMMON_EXPORT+=",PICKLE_PATH=$PICKLE_PATH,PAPER_RECORDS_PATH=${PAPER_RECORDS_PATH:-$PICKLE_PATH}"
fi
for key in TAXONOMY_PATH CHECKPOINT_DIR SHARD_SIZE EXTRACT_SHARD_SIZE CONCURRENCY EXTRACTION_CONCURRENCY \
           CEMENTITIOUS_WORKERS CEMENTITIOUS_BATCH_SIZE CEMENTITIOUS_MAX_IN_FLIGHT \
           CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB CEMENTITIOUS_MAX_RECORDS ARRAY_MAX_CONCURRENCY \
           TOP_N TOP_N_SOURCES WEB_LIMIT RUN_MODE FORCE RESUME KEYWORD_ONLY \
           SELECTED_SUBCATEGORIES SELECTED_SUB_SUBCATEGORIES LITERATURE_ONLY WEB_ONLY \
           TOP_N_PER_SUBCATEGORY TOP_N_PER_SUB_SUBCATEGORY SKIP_QC CCS_MIGRATE_INPUT \
           OPENAI_API_KEY TAVILY_API_KEY \
           WEB_QUERIES_PER_SUBCATEGORY WEB_QUERIES_PER_SUB_SUBCATEGORY WEB_RESULTS_PER_QUERY \
           WEB_MAX_URLS_PER_BRANCH WEB_MAX_TOTAL_URLS WEB_SEARCH_SHARD_SIZE WEB_EXTRACT_SHARD_SIZE \
           WEB_CONCURRENCY WEB_REQUEST_TIMEOUT WEB_MAX_RETRIES WEB_PAGE_MAX_CHARS \
           WEB_DOMAIN_ALLOWLIST WEB_DOMAIN_DENYLIST; do
  if [[ -n "${!key:-}" ]]; then
    COMMON_EXPORT+=",${key}=${!key}"
  fi
done

echo "Orchestrator: ranking + planning literature extraction shards (FINALIZE_LITERATURE=$FINALIZE_LITERATURE)"
bash "$REPO_ROOT/scripts/engaging/730_cementitious_rank_plan_extract.sh"

EXTRACT_RANGE="$(tr -d '[:space:]' < "$OUT/metadata/extract_array_range.txt" || true)"
ARRAY_MAX_CONCURRENCY="${ARRAY_MAX_CONCURRENCY:-1}"
if [[ -n "$EXTRACT_RANGE" && "$EXTRACT_RANGE" != *%* ]]; then
  EXTRACT_RANGE="${EXTRACT_RANGE}%${ARRAY_MAX_CONCURRENCY}"
fi
declare -a SUBMITTED_NAMES=()
declare -a SUBMITTED_IDS=()

record_job() {
  SUBMITTED_NAMES+=("$1")
  SUBMITTED_IDS+=("$2")
  echo "Submitted $1 -> $2"
}

join_deps() {
  local first=1 out="afterok"
  for id in "$@"; do
    [[ -z "$id" ]] && continue
    id="${id%%_*}"
    if [[ "$first" -eq 1 ]]; then
      out="afterok:${id}"
      first=0
    else
      out="${out}:${id}"
    fi
  done
  [[ "$first" -eq 1 ]] && echo "" || echo "$out"
}

submit_login() {
  local job_name="$1"
  local cmd="$2"
  shift 2
  local mem="${SUBMIT_LOGIN_MEM:-16G}"
  sbatch --parsable \
    --chdir="$REPO_ROOT" \
    --job-name="$job_name" \
    --output="logs/${job_name}-%j.out" \
    --time=04:00:00 \
    --cpus-per-task=1 \
    --mem="$mem" \
    --export="$COMMON_EXPORT" \
    "$@" \
    --wrap="cd \"$REPO_ROOT\" && export REPO_ROOT=\"$REPO_ROOT\" && export CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB=\${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-12.8} && $cmd"
}

prev_dep=""

if [[ -z "$EXTRACT_RANGE" ]]; then
  echo "No extraction shards (zero relevant candidates). Skipping extract array."
  merge_extract_job=$(submit_login cm-merge-extract \
    "bash scripts/engaging/730_cementitious_merge_extractions.sh")
  record_job extract_merge "$merge_extract_job"
  prev_dep=$(join_deps "$merge_extract_job")
else
  echo "Submitting extract array: --array=$EXTRACT_RANGE"
  extract_job=$(sbatch --parsable \
    --chdir="$REPO_ROOT" \
    --export="$COMMON_EXPORT" \
    --array="$EXTRACT_RANGE" \
    "$REPO_ROOT/scripts/engaging/730_cementitious_extract_array.sh")
  record_job extract "$extract_job"
  prev_dep=$(join_deps "$extract_job")

  dep_args=(--dependency="$prev_dep")
  merge_extract_job=$(submit_login cm-merge-extract \
    "bash scripts/engaging/730_cementitious_merge_extractions.sh" \
    "${dep_args[@]}")
  record_job extract_merge "$merge_extract_job"
  prev_dep=$(join_deps "$merge_extract_job")
fi

if [[ "$FINALIZE_LITERATURE" == "1" ]]; then
  dep_args=(--dependency="$prev_dep")
  dedupe_job=$(submit_login cm-dedupe-qc \
    "bash scripts/engaging/730_cementitious_dedupe_qc.sh" \
    "${dep_args[@]}")
  record_job dedupe_qc "$dedupe_job"
  prev_dep=$(join_deps "$dedupe_job")

  if [[ -n "${CCS_MIGRATE_INPUT:-}" ]]; then
    dep_args=(--dependency="$prev_dep")
    mig_job=$(submit_login cm-migrate-ccs \
      "python -m pipeline.cementitious.cluster migrate-carbon-capture --input \"$CCS_MIGRATE_INPUT\" --output \"$OUT\"" \
      "${dep_args[@]}")
    record_job migrate_ccs "$mig_job"
    prev_dep=$(join_deps "$mig_job")
  fi

  dep_args=(--dependency="$prev_dep")
  export_job=$(submit_login cm-export \
    "FORCE=${FORCE:-0} bash scripts/engaging/730_cementitious_export.sh" \
    "${dep_args[@]}")
  record_job export "$export_job"
fi

# Terminal literature job for combined-mode finalize afterok chaining
# Prefer merge-extract job id (last literature branch stage before combined merge)
TERMINAL_ID="${merge_extract_job:-}"
if [[ -n "$TERMINAL_ID" ]]; then
  echo "${TERMINAL_ID%%_*}" > "$OUT/metadata/literature_terminal_job_id.txt"
  echo "Wrote literature_terminal_job_id=${TERMINAL_ID%%_*}"
fi

# Append downstream job IDs
JOBS_JSON="$OUT/metadata/submitted_jobs.json"
JOBS_TXT="$OUT/metadata/submitted_jobs.txt"
python - "$JOBS_JSON" "$JOBS_TXT" "$OUT" "${SUBMITTED_NAMES[@]}" -- "${SUBMITTED_IDS[@]}" <<'PY'
import json, sys
from pathlib import Path
json_path, txt_path, out = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
args = sys.argv[4:]
idx = args.index("--")
names, ids = args[:idx], args[idx+1:]
jobs = [{"name": n, "job_id": i} for n, i in zip(names, ids)]
payload = {}
if json_path.is_file():
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
if not isinstance(payload, dict):
    payload = {}
existing = list(payload.get("jobs") or [])
existing.extend(jobs)
payload["output_dir"] = out
payload["literature_downstream_jobs"] = jobs
payload["jobs"] = existing
json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
with txt_path.open("a", encoding="utf-8") as handle:
    handle.write("\n# literature downstream (orchestrator)\n")
    for j in jobs:
        handle.write(f"{j['name']}: {j['job_id']}\n")
print(json.dumps(jobs, indent=2))
PY

echo "Literature orchestrator finished submitting jobs."
