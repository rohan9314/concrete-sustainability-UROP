#!/bin/bash
# MIT Engaging — web branch orchestration (runs as a Slurm job after web-search array):
#   1) merge-web-search (sync)
#   2) plan-web-extract (sync; writes web_extract_array_range.txt)
#   3) submit web-extract array + merge-web-extract
#   4) if FINALIZE_WEB=1 (web-only): merge-literature-web → dedupe → export
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"
mkdir -p logs

: "${RESULTS_ROOT:?Set RESULTS_ROOT}"
# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
source "$_SCRIPT_DIR/_resolve_cementitious_out.sh"
resolve_cementitious_out || exit 1
RUN_MODE="${RUN_MODE:-web-only}"
FINALIZE_WEB="${FINALIZE_WEB:-0}"
if [[ "$RUN_MODE" == "web-only" || "$RUN_MODE" == "web_only" ]]; then
  FINALIZE_WEB=1
fi

COMMON_EXPORT="${COMMON_EXPORT:-ALL,REPO_ROOT=$REPO_ROOT,RESULTS_ROOT=$RESULTS_ROOT}"
for key in TAXONOMY_PATH CHECKPOINT_DIR RUN_MODE FORCE RESUME KEYWORD_ONLY \
           SELECTED_SUBCATEGORIES SELECTED_SUB_SUBCATEGORIES LITERATURE_ONLY WEB_ONLY \
           SKIP_QC CCS_MIGRATE_INPUT OPENAI_API_KEY TAVILY_API_KEY \
           WEB_QUERIES_PER_SUBCATEGORY WEB_QUERIES_PER_SUB_SUBCATEGORY WEB_RESULTS_PER_QUERY \
           WEB_MAX_URLS_PER_BRANCH WEB_MAX_TOTAL_URLS WEB_SEARCH_SHARD_SIZE WEB_EXTRACT_SHARD_SIZE \
           WEB_CONCURRENCY WEB_REQUEST_TIMEOUT WEB_MAX_RETRIES WEB_PAGE_MAX_CHARS \
           WEB_DOMAIN_ALLOWLIST WEB_DOMAIN_DENYLIST WEB_LIMIT; do
  if [[ -n "${!key:-}" ]]; then
    COMMON_EXPORT+=",${key}=${!key}"
  fi
done

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
  sbatch --parsable \
    --job-name="$job_name" \
    --output="logs/${job_name}-%j.out" \
    --time=04:00:00 \
    --cpus-per-task=2 \
    --mem=8G \
    --export="$COMMON_EXPORT" \
    "$@" \
    --wrap="cd \"$REPO_ROOT\" && $cmd"
}

echo "Web orchestrator: merge search + plan extract (FINALIZE_WEB=$FINALIZE_WEB)"
bash "$_SCRIPT_DIR/730_cementitious_merge_web_search.sh"
bash "$_SCRIPT_DIR/730_cementitious_plan_web_extract.sh"

EXTRACT_RANGE="$(tr -d '[:space:]' < "$OUT/metadata/web_extract_array_range.txt" || true)"
prev_dep=""

if [[ -z "$EXTRACT_RANGE" ]]; then
  echo "No web extraction shards. Running empty merge-web-extract."
  merge_ex_job=$(submit_login cm-merge-web-extract \
    "bash scripts/engaging/730_cementitious_merge_web_extract.sh")
  record_job web_extract_merge "$merge_ex_job"
  prev_dep=$(join_deps "$merge_ex_job")
else
  echo "Submitting web-extract array: --array=$EXTRACT_RANGE"
  extract_job=$(sbatch --parsable \
    --export="$COMMON_EXPORT" \
    --array="$EXTRACT_RANGE" \
    "$_SCRIPT_DIR/730_cementitious_web_extract_array.sh")
  record_job web_extract "$extract_job"
  prev_dep=$(join_deps "$extract_job")

  merge_ex_job=$(submit_login cm-merge-web-extract \
    "bash scripts/engaging/730_cementitious_merge_web_extract.sh" \
    --dependency="$prev_dep")
  record_job web_extract_merge "$merge_ex_job"
  prev_dep=$(join_deps "$merge_ex_job")
fi

if [[ "$FINALIZE_WEB" == "1" ]]; then
  merge_lw_job=$(submit_login cm-merge-lit-web \
    "bash scripts/engaging/730_cementitious_merge_literature_web.sh" \
    --dependency="$prev_dep")
  record_job merge_literature_web "$merge_lw_job"
  prev_dep=$(join_deps "$merge_lw_job")

  dedupe_job=$(submit_login cm-dedupe-qc \
    "bash scripts/engaging/730_cementitious_dedupe_qc.sh" \
    --dependency="$prev_dep")
  record_job dedupe_qc "$dedupe_job"
  prev_dep=$(join_deps "$dedupe_job")

  if [[ -n "${CCS_MIGRATE_INPUT:-}" ]]; then
    mig_job=$(submit_login cm-migrate-ccs \
      "python -m pipeline.cementitious.cluster migrate-carbon-capture --input \"$CCS_MIGRATE_INPUT\" --output \"$OUT\"" \
      --dependency="$prev_dep")
    record_job migrate_ccs "$mig_job"
    prev_dep=$(join_deps "$mig_job")
  fi

  export_job=$(submit_login cm-export \
    "FORCE=${FORCE:-0} bash scripts/engaging/730_cementitious_export.sh" \
    --dependency="$prev_dep")
  record_job export "$export_job"
fi

# Terminal web job for combined-mode finalize afterok chaining
TERMINAL_ID="${merge_ex_job:-}"
if [[ -n "$TERMINAL_ID" ]]; then
  echo "${TERMINAL_ID%%_*}" > "$OUT/metadata/web_terminal_job_id.txt"
  echo "Wrote web_terminal_job_id=${TERMINAL_ID%%_*}"
fi

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
payload["web_downstream_jobs"] = jobs
payload["jobs"] = existing
json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
with txt_path.open("a", encoding="utf-8") as handle:
    handle.write("\n# web downstream (orchestrator)\n")
    for j in jobs:
        handle.write(f"{j['name']}: {j['job_id']}\n")
print(json.dumps(jobs, indent=2))
PY

echo "Web orchestrator finished submitting jobs."
