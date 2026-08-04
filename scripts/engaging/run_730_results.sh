#!/bin/bash
# One-command Engaging launcher for genuinely sharded Cementitious Materials runs.
#
# Modes:
#   literature-only      — literature branch only (no Tavily)
#   web-only             — web branch only (PICKLE_PATH optional)
#   literature-and-web   — both branches, then merge → dedupe → export
#
# Prerequisites:
#   export OPENAI_API_KEY="..."
#   export TAVILY_API_KEY="..."   # required unless literature-only
#   export PICKLE_PATH="..."      # required unless web-only
#   export RESULTS_ROOT="..."
#
set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }

_LAUNCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${REPO_ROOT:-}" ]] && command -v git >/dev/null 2>&1; then
  if _git_root="$(git -C "$_LAUNCH_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
    REPO_ROOT="$_git_root"
  fi
fi
if [[ -z "${REPO_ROOT:-}" ]]; then
  REPO_ROOT="$(cd "$_LAUNCH_DIR/../.." && pwd)"
fi
# shellcheck source=scripts/engaging/_cementitious_repo_root.sh
source "$REPO_ROOT/scripts/engaging/_cementitious_repo_root.sh"
cementitious_resolve_repo_root "run_730_results" || exit 1
cd "$REPO_ROOT"
export REPO_ROOT
ENGAGING_SCRIPTS="$REPO_ROOT/scripts/engaging"
mkdir -p logs

export SHARD_SIZE="${SHARD_SIZE:-10000}"
export EXTRACT_SHARD_SIZE="${EXTRACT_SHARD_SIZE:-25}"
export CONCURRENCY="${CONCURRENCY:-${EXTRACTION_CONCURRENCY:-1}}"
export EXTRACTION_CONCURRENCY="${EXTRACTION_CONCURRENCY:-$CONCURRENCY}"
export CEMENTITIOUS_WORKERS="${CEMENTITIOUS_WORKERS:-1}"
export CEMENTITIOUS_BATCH_SIZE="${CEMENTITIOUS_BATCH_SIZE:-25}"
export CEMENTITIOUS_MAX_IN_FLIGHT="${CEMENTITIOUS_MAX_IN_FLIGHT:-1}"
export CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB="${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-}"
export ARRAY_MAX_CONCURRENCY="${ARRAY_MAX_CONCURRENCY:-1}"
export TOP_N="${TOP_N:-${TOP_N_SOURCES:-50}}"
export TOP_N_SOURCES="${TOP_N_SOURCES:-$TOP_N}"
export WEB_LIMIT="${WEB_LIMIT:-50}"
export WEB_QUERIES_PER_SUBCATEGORY="${WEB_QUERIES_PER_SUBCATEGORY:-3}"
export WEB_QUERIES_PER_SUB_SUBCATEGORY="${WEB_QUERIES_PER_SUB_SUBCATEGORY:-5}"
export WEB_RESULTS_PER_QUERY="${WEB_RESULTS_PER_QUERY:-10}"
export WEB_MAX_URLS_PER_BRANCH="${WEB_MAX_URLS_PER_BRANCH:-50}"
export WEB_MAX_TOTAL_URLS="${WEB_MAX_TOTAL_URLS:-1000}"
export WEB_SEARCH_SHARD_SIZE="${WEB_SEARCH_SHARD_SIZE:-10}"
export WEB_EXTRACT_SHARD_SIZE="${WEB_EXTRACT_SHARD_SIZE:-10}"
export WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"
export WEB_REQUEST_TIMEOUT="${WEB_REQUEST_TIMEOUT:-30}"
export WEB_MAX_RETRIES="${WEB_MAX_RETRIES:-3}"
export WEB_PAGE_MAX_CHARS="${WEB_PAGE_MAX_CHARS:-50000}"
export RUN_MODE="${RUN_MODE:-literature-and-web}"
export EXECUTION_MODE="${EXECUTION_MODE:-submit}"
export FORCE="${FORCE:-0}"
export RESUME="${RESUME:-0}"
export DRY_RUN="${DRY_RUN:-0}"
export LITERATURE_ONLY="${LITERATURE_ONLY:-0}"
export WEB_ONLY="${WEB_ONLY:-0}"
export KEYWORD_ONLY="${KEYWORD_ONLY:-0}"

if [[ "$LITERATURE_ONLY" == "1" ]]; then RUN_MODE="literature-only"; fi
if [[ "$WEB_ONLY" == "1" ]]; then RUN_MODE="web-only"; fi
export RUN_MODE

case "$RUN_MODE" in
  literature-only|literature_only) NEED_LIT=1; NEED_WEB=0 ;;
  web-only|web_only) NEED_LIT=0; NEED_WEB=1 ;;
  literature-and-web|literature_and_web) NEED_LIT=1; NEED_WEB=1 ;;
  *) echo "ERROR: unknown RUN_MODE=$RUN_MODE" >&2; exit 1 ;;
esac

if [[ -z "${PICKLE_PATH:-}" && -n "${PAPER_RECORDS_PATH:-}" ]]; then
  export PICKLE_PATH="$PAPER_RECORDS_PATH"
fi
if [[ -n "${PICKLE_PATH:-}" && -z "${PAPER_RECORDS_PATH:-}" ]]; then
  export PAPER_RECORDS_PATH="$PICKLE_PATH"
fi

[[ -n "${OPENAI_API_KEY:-}" ]] || die "OPENAI_API_KEY is required"
[[ -n "${RESULTS_ROOT:-}" ]] || die "RESULTS_ROOT is required"

if [[ "$NEED_LIT" -eq 1 ]]; then
  [[ -n "${PICKLE_PATH:-}" ]] || die "PICKLE_PATH or PAPER_RECORDS_PATH is required for literature modes"
  [[ -f "$PICKLE_PATH" ]] || die "PICKLE_PATH is not a readable file: $PICKLE_PATH"
fi

if [[ "$NEED_WEB" -eq 1 ]]; then
  [[ -n "${TAVILY_API_KEY:-}" ]] || die "TAVILY_API_KEY is required when web retrieval is enabled"
fi

mkdir -p "$RESULTS_ROOT"
# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
cementitious_source_engaging_helper "_resolve_cementitious_out.sh" "run_730_results" || exit 1
resolve_cementitious_out || exit 1
mkdir -p "$OUT"
mkdir -p "$OUT"/{all_records,subcategories,sub_subcategories,citations/subcategories,citations/sub_subcategories,pending_taxonomy_review,logs,checkpoints,rejected_records,metadata}
printf '%s\n' "$REPO_ROOT" >"$OUT/metadata/repo_root.txt"
mkdir -p "$OUT/metadata/screening_shards" "$OUT/checkpoints/screen_shards"
mkdir -p "$OUT/metadata/extraction_shards" "$OUT/checkpoints/extraction_shards"
mkdir -p "$OUT/metadata/web_search_shards" "$OUT/checkpoints/web_search_shards"
mkdir -p "$OUT/metadata/web_extraction_shards" "$OUT/checkpoints/web_extraction_shards"
export CHECKPOINT_DIR="${CHECKPOINT_DIR:-$OUT/checkpoints}"

if [[ -n "${TAXONOMY_PATH:-}" ]]; then
  [[ -f "$TAXONOMY_PATH" ]] || die "TAXONOMY_PATH not found: $TAXONOMY_PATH"
else
  if [[ -f "$REPO_ROOT/config/cementitious_materials_taxonomy.json" ]]; then
    export TAXONOMY_PATH="$REPO_ROOT/config/cementitious_materials_taxonomy.json"
  elif [[ -f "$REPO_ROOT/config/cementitious_materials_taxonomy.yaml" ]]; then
    export TAXONOMY_PATH="$REPO_ROOT/config/cementitious_materials_taxonomy.yaml"
  else
    die "Taxonomy config not found under config/"
  fi
fi

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  if [[ -f "$REPO_ROOT/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.venv/bin/activate"
  elif [[ -f "$REPO_ROOT/venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$REPO_ROOT/venv/bin/activate"
  fi
fi

PYTHON_BIN="$(command -v python3 || command -v python)" || die "python not found"
"$PYTHON_BIN" - <<'PY'
import importlib
for mod in ("openai", "dotenv"):
    importlib.import_module(mod)
print("Required Python packages: ok")
PY

echo "======== Cementitious Materials / 7-30 results (sharded) ========"
echo "REPO_ROOT=$REPO_ROOT"
echo "RESULTS_ROOT=$RESULTS_ROOT"
echo "OUT=$OUT"
echo "PICKLE_PATH=${PICKLE_PATH:-<not required for web-only>}"
echo "TAXONOMY_PATH=$TAXONOMY_PATH"
echo "RUN_MODE=$RUN_MODE EXECUTION_MODE=$EXECUTION_MODE NEED_LIT=$NEED_LIT NEED_WEB=$NEED_WEB"
echo "SHARD_SIZE=$SHARD_SIZE EXTRACT_SHARD_SIZE=$EXTRACT_SHARD_SIZE"
echo "TOP_N=$TOP_N WEB_LIMIT=$WEB_LIMIT CONCURRENCY=$CONCURRENCY"
echo "WEB_QUERIES_PER_SUBCATEGORY=$WEB_QUERIES_PER_SUBCATEGORY"
echo "WEB_QUERIES_PER_SUB_SUBCATEGORY=$WEB_QUERIES_PER_SUB_SUBCATEGORY"
echo "WEB_RESULTS_PER_QUERY=$WEB_RESULTS_PER_QUERY"
echo "WEB_MAX_URLS_PER_BRANCH=$WEB_MAX_URLS_PER_BRANCH"
echo "WEB_MAX_TOTAL_URLS=$WEB_MAX_TOTAL_URLS"
echo "WEB_SEARCH_SHARD_SIZE=$WEB_SEARCH_SHARD_SIZE WEB_EXTRACT_SHARD_SIZE=$WEB_EXTRACT_SHARD_SIZE"
echo "WEB_CONCURRENCY=$WEB_CONCURRENCY WEB_REQUEST_TIMEOUT=$WEB_REQUEST_TIMEOUT WEB_MAX_RETRIES=$WEB_MAX_RETRIES"
echo "WEB_PAGE_MAX_CHARS=$WEB_PAGE_MAX_CHARS"
echo "WEB_DOMAIN_ALLOWLIST=${WEB_DOMAIN_ALLOWLIST:-<none>}"
echo "WEB_DOMAIN_DENYLIST=${WEB_DOMAIN_DENYLIST:-<none>}"
echo "SELECTED_SUBCATEGORIES=${SELECTED_SUBCATEGORIES:-<all>}"
echo "SELECTED_SUB_SUBCATEGORIES=${SELECTED_SUB_SUBCATEGORIES:-<all>}"
echo "RESUME=$RESUME FORCE=$FORCE DRY_RUN=$DRY_RUN KEYWORD_ONLY=$KEYWORD_ONLY"
echo "OPENAI_API_KEY: set"
echo "TAVILY_API_KEY: $([ -n "${TAVILY_API_KEY:-}" ] && echo set || echo unset)"
echo "==============================================================="

"$PYTHON_BIN" -m pipeline.run_cementitious_materials validate-taxonomy --taxonomy-path "$TAXONOMY_PATH"

# Do not unpickle the full corpus here — materialization happens in plan/preprocess.
if [[ "$NEED_LIT" -eq 1 ]]; then
  echo "PICKLE_PATH exists ($(wc -c < "$PICKLE_PATH" | tr -d ' ') bytes); full load deferred to plan-screen."
fi

# Legacy WEB_LIMIT mirrors into WEB_MAX_TOTAL_URLS only when the caller did not set WEB_MAX_TOTAL_URLS.
if [[ -n "${WEB_LIMIT:-}" && -z "${WEB_MAX_TOTAL_URLS+x}" ]]; then
  export WEB_MAX_TOTAL_URLS="$WEB_LIMIT"
fi

apply_array_concurrency() {
  local range="$1"
  local cap="${ARRAY_MAX_CONCURRENCY:-1}"
  if [[ -z "$range" ]]; then
    echo ""
    return
  fi
  if [[ "$range" == *%* ]]; then
    echo "$range"
    return
  fi
  echo "${range}%${cap}"
}

SCREEN_RANGE=""
WEB_SEARCH_RANGE=""

if [[ "$NEED_LIT" -eq 1 ]]; then
  if [[ "${SKIP_LIT_PLAN:-0}" == "1" ]]; then
    echo "SKIP_LIT_PLAN=1 — reusing corpus shards / screen plan from preprocess job"
    [[ -f "$OUT/checkpoints/plan_screen.complete" ]] || die "missing plan_screen.complete; preprocess did not finish"
    [[ -f "$OUT/metadata/screen_array_range.txt" ]] || die "missing screen_array_range.txt"
    [[ -f "$OUT/metadata/corpus_shards_manifest.json" ]] || die "missing corpus_shards_manifest.json (memory-safe shards required)"
  else
    echo "Running synchronous plan-screen (materializes corpus JSONL shards; high RAM)..."
    bash "$ENGAGING_SCRIPTS/730_cementitious_plan.sh"
  fi
  SCREEN_RANGE="$(tr -d '[:space:]' < "$OUT/metadata/screen_array_range.txt")"
  [[ -n "$SCREEN_RANGE" ]] || die "screen_array_range.txt is empty; refusing default 0-0"
  if [[ -n "${SCREEN_ARRAY_OVERRIDE:-}" ]]; then
    echo "WARNING: SCREEN_ARRAY_OVERRIDE=${SCREEN_ARRAY_OVERRIDE} (debug only)"
    SCREEN_RANGE="$SCREEN_ARRAY_OVERRIDE"
  fi
  SCREEN_RANGE="$(apply_array_concurrency "$SCREEN_RANGE")"
  echo "Derived SCREEN_ARRAY=$SCREEN_RANGE (ARRAY_MAX_CONCURRENCY=$ARRAY_MAX_CONCURRENCY)"
fi

if [[ "$NEED_WEB" -eq 1 ]]; then
  echo "Running synchronous plan-web-queries..."
  bash "$ENGAGING_SCRIPTS/730_cementitious_plan_web_queries.sh"
  WEB_SEARCH_RANGE="$(tr -d '[:space:]' < "$OUT/metadata/web_search_array_range.txt" || true)"
  if [[ -n "${WEB_SEARCH_ARRAY_OVERRIDE:-}" ]]; then
    echo "WARNING: WEB_SEARCH_ARRAY_OVERRIDE=${WEB_SEARCH_ARRAY_OVERRIDE} (debug only)"
    WEB_SEARCH_RANGE="$WEB_SEARCH_ARRAY_OVERRIDE"
  fi
  WEB_SEARCH_RANGE="$(apply_array_concurrency "$WEB_SEARCH_RANGE")"
  echo "Derived WEB_SEARCH_ARRAY=${WEB_SEARCH_RANGE:-<empty>}"
fi

# Refuse silent overwrite of a completed production export unless FORCE=1.
if [[ -f "$OUT/checkpoints/export.complete" && "${FORCE:-0}" != "1" && "${DRY_RUN:-0}" != "1" ]]; then
  die "Completed export exists at $OUT/checkpoints/export.complete; set FORCE=1 to overwrite"
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY_RUN=1 — plan complete; not submitting jobs."
  [[ -n "$SCREEN_RANGE" ]] && echo "Would submit screen array: $SCREEN_RANGE"
  [[ -n "$WEB_SEARCH_RANGE" ]] && echo "Would submit web-search array: $WEB_SEARCH_RANGE"
  exit 0
fi

# Combined mode must keep web enabled.
if [[ "$NEED_LIT" -eq 1 && "$NEED_WEB" -eq 1 ]]; then
  [[ -n "${TAVILY_API_KEY:-}" ]] || die "TAVILY_API_KEY required for literature-and-web"
fi

COMMON_EXPORT="ALL,REPO_ROOT=$REPO_ROOT,RESULTS_ROOT=$RESULTS_ROOT"
if [[ -n "${PICKLE_PATH:-}" ]]; then
  COMMON_EXPORT+=",PICKLE_PATH=$PICKLE_PATH,PAPER_RECORDS_PATH=${PAPER_RECORDS_PATH:-$PICKLE_PATH}"
fi
COMMON_EXPORT+=",TAXONOMY_PATH=$TAXONOMY_PATH,CHECKPOINT_DIR=$CHECKPOINT_DIR"
COMMON_EXPORT+=",SHARD_SIZE=$SHARD_SIZE,EXTRACT_SHARD_SIZE=$EXTRACT_SHARD_SIZE"
COMMON_EXPORT+=",CONCURRENCY=$CONCURRENCY,EXTRACTION_CONCURRENCY=$EXTRACTION_CONCURRENCY"
COMMON_EXPORT+=",CEMENTITIOUS_WORKERS=$CEMENTITIOUS_WORKERS,CEMENTITIOUS_BATCH_SIZE=$CEMENTITIOUS_BATCH_SIZE"
COMMON_EXPORT+=",CEMENTITIOUS_MAX_IN_FLIGHT=$CEMENTITIOUS_MAX_IN_FLIGHT"
COMMON_EXPORT+=",CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB=${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-}"
COMMON_EXPORT+=",CEMENTITIOUS_MAX_RECORDS=${CEMENTITIOUS_MAX_RECORDS:-}"
COMMON_EXPORT+=",ARRAY_MAX_CONCURRENCY=$ARRAY_MAX_CONCURRENCY"
COMMON_EXPORT+=",TOP_N=$TOP_N,TOP_N_SOURCES=$TOP_N_SOURCES,WEB_LIMIT=$WEB_LIMIT"
COMMON_EXPORT+=",RUN_MODE=$RUN_MODE,FORCE=$FORCE,RESUME=$RESUME,KEYWORD_ONLY=$KEYWORD_ONLY"
COMMON_EXPORT+=",SELECTED_SUBCATEGORIES=${SELECTED_SUBCATEGORIES:-},SELECTED_SUB_SUBCATEGORIES=${SELECTED_SUB_SUBCATEGORIES:-}"
COMMON_EXPORT+=",LITERATURE_ONLY=$LITERATURE_ONLY,WEB_ONLY=$WEB_ONLY"
COMMON_EXPORT+=",TOP_N_PER_SUBCATEGORY=${TOP_N_PER_SUBCATEGORY:-},TOP_N_PER_SUB_SUBCATEGORY=${TOP_N_PER_SUB_SUBCATEGORY:-}"
COMMON_EXPORT+=",SKIP_QC=${SKIP_QC:-0}"
COMMON_EXPORT+=",WEB_QUERIES_PER_SUBCATEGORY=$WEB_QUERIES_PER_SUBCATEGORY"
COMMON_EXPORT+=",WEB_QUERIES_PER_SUB_SUBCATEGORY=$WEB_QUERIES_PER_SUB_SUBCATEGORY"
COMMON_EXPORT+=",WEB_RESULTS_PER_QUERY=$WEB_RESULTS_PER_QUERY"
COMMON_EXPORT+=",WEB_MAX_URLS_PER_BRANCH=$WEB_MAX_URLS_PER_BRANCH"
COMMON_EXPORT+=",WEB_MAX_TOTAL_URLS=$WEB_MAX_TOTAL_URLS"
COMMON_EXPORT+=",WEB_SEARCH_SHARD_SIZE=$WEB_SEARCH_SHARD_SIZE"
COMMON_EXPORT+=",WEB_EXTRACT_SHARD_SIZE=$WEB_EXTRACT_SHARD_SIZE"
COMMON_EXPORT+=",WEB_CONCURRENCY=$WEB_CONCURRENCY"
COMMON_EXPORT+=",WEB_REQUEST_TIMEOUT=$WEB_REQUEST_TIMEOUT"
COMMON_EXPORT+=",WEB_MAX_RETRIES=$WEB_MAX_RETRIES"
COMMON_EXPORT+=",WEB_PAGE_MAX_CHARS=$WEB_PAGE_MAX_CHARS"
COMMON_EXPORT+=",WEB_DOMAIN_ALLOWLIST=${WEB_DOMAIN_ALLOWLIST:-}"
COMMON_EXPORT+=",WEB_DOMAIN_DENYLIST=${WEB_DOMAIN_DENYLIST:-}"
COMMON_EXPORT+=",OPENAI_API_KEY=$OPENAI_API_KEY"
if [[ -n "${TAVILY_API_KEY:-}" ]]; then
  COMMON_EXPORT+=",TAVILY_API_KEY=$TAVILY_API_KEY"
fi
if [[ -n "${CCS_MIGRATE_INPUT:-}" ]]; then
  COMMON_EXPORT+=",CCS_MIGRATE_INPUT=$CCS_MIGRATE_INPUT"
fi
export COMMON_EXPORT

declare -a SUBMITTED_IDS=()
declare -a SUBMITTED_NAMES=()

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

if [[ "$EXECUTION_MODE" == "interactive" ]]; then
  echo "EXECUTION_MODE=interactive — running stages in-process."
  "$PYTHON_BIN" - <<PY
import json
from pathlib import Path
from pipeline.cementitious.stages import (
    screen_shard, merge_screening, rank_and_plan_extraction,
    extract_shard, merge_extractions, dedupe_and_qc, export_final,
)
from pipeline.cementitious.web_stages import (
    plan_web_query_shards, web_search_shard, merge_web_search,
    plan_web_extraction, web_extract_shard, merge_web_extractions,
    merge_literature_and_web,
)
out = Path(r"""$OUT""")
resume = r"""$RESUME""" == "1"
keyword = r"""$KEYWORD_ONLY""" == "1"
need_lit = int(r"""$NEED_LIT""")
need_web = int(r"""$NEED_WEB""")
if need_lit:
    shards = json.loads((out / "metadata" / "screen_shards.json").read_text())
    for entry in shards:
        screen_shard(shard_id=int(entry["shard_id"]), output_dir=out, resume=resume, keyword_only=keyword)
    merge_screening(output_dir=out)
    rank_and_plan_extraction(output_dir=out)
    extract_shards = json.loads((out / "metadata" / "extraction_shards.json").read_text())
    for entry in extract_shards:
        extract_shard(shard_id=int(entry["shard_id"]), output_dir=out, resume=resume, keyword_only=keyword)
    merge_extractions(output_dir=out)
if need_web:
    # plan may already have been run by launcher
    if not (out / "metadata" / "web_query_shards.json").is_file():
        plan_web_query_shards(output_dir=out)
    wshards = json.loads((out / "metadata" / "web_query_shards.json").read_text())
    for entry in wshards:
        web_search_shard(shard_id=int(entry["shard_id"]), output_dir=out, resume=resume)
    merge_web_search(output_dir=out)
    plan_web_extraction(output_dir=out)
    eshards = json.loads((out / "metadata" / "web_extraction_shards.json").read_text())
    for entry in eshards:
        web_extract_shard(shard_id=int(entry["shard_id"]), output_dir=out, resume=resume, keyword_only=keyword)
    merge_web_extractions(output_dir=out)
if need_lit and need_web:
    merge_literature_and_web(output_dir=out)
elif need_web and not need_lit:
    merge_literature_and_web(output_dir=out)
dedupe_and_qc(output_dir=out, keyword_only=keyword)
export_final(output_dir=out, force=r"""$FORCE""" == "1")
print("interactive sharded run complete")
PY
  echo "Expected final results directory: $OUT"
  exit 0
fi

lit_orch_job=""
web_orch_job=""

# ── Literature branch ────────────────────────────────────────────────────────
if [[ "$NEED_LIT" -eq 1 ]]; then
  screen_job=$(sbatch --parsable \
    --chdir="$REPO_ROOT" \
    --export="$COMMON_EXPORT" \
    --array="$SCREEN_RANGE" \
    "$ENGAGING_SCRIPTS/730_cementitious_screen_array.sh")
  record_job screen "$screen_job"
  lit_dep=$(join_deps "$screen_job")

  merge_screen_job=$(submit_login cm-merge-screen \
    "bash scripts/engaging/730_cementitious_merge_screening.sh" \
    --dependency="$lit_dep")
  record_job screen_merge "$merge_screen_job"
  lit_dep=$(join_deps "$merge_screen_job")

  lit_orch_job=$(submit_login cm-orchestrate-lit \
    "COMMON_EXPORT='$COMMON_EXPORT' bash scripts/engaging/730_cementitious_orchestrate_after_screen.sh" \
    --dependency="$lit_dep")
  record_job lit_orchestrate "$lit_orch_job"
fi

# ── Web branch ───────────────────────────────────────────────────────────────
if [[ "$NEED_WEB" -eq 1 ]]; then
  if [[ -n "$WEB_SEARCH_RANGE" ]]; then
    web_search_job=$(sbatch --parsable \
      --chdir="$REPO_ROOT" \
      --export="$COMMON_EXPORT" \
      --array="$WEB_SEARCH_RANGE" \
      "$ENGAGING_SCRIPTS/730_cementitious_web_search_array.sh")
    record_job web_search "$web_search_job"
    web_dep=$(join_deps "$web_search_job")
  else
    echo "WARNING: no web search shards (empty query plan); web orchestrator will merge empty set"
    web_dep=""
  fi

  if [[ -n "${web_dep:-}" ]]; then
    web_orch_job=$(submit_login cm-orchestrate-web \
      "COMMON_EXPORT='$COMMON_EXPORT' bash scripts/engaging/730_cementitious_orchestrate_web.sh" \
      --dependency="$web_dep")
  else
    web_orch_job=$(submit_login cm-orchestrate-web \
      "COMMON_EXPORT='$COMMON_EXPORT' bash scripts/engaging/730_cementitious_orchestrate_web.sh")
  fi
  record_job web_orchestrate "$web_orch_job"
fi

# ── Combined finalize ────────────────────────────────────────────────────────
if [[ "$NEED_LIT" -eq 1 && "$NEED_WEB" -eq 1 ]]; then
  fin_dep=$(join_deps "$lit_orch_job" "$web_orch_job")
  finalize_job=$(submit_login cm-finalize \
    "COMMON_EXPORT='$COMMON_EXPORT' bash scripts/engaging/730_cementitious_finalize.sh" \
    --dependency="$fin_dep")
  record_job finalize "$finalize_job"
fi

JOBS_JSON="$OUT/metadata/submitted_jobs.json"
JOBS_TXT="$OUT/metadata/submitted_jobs.txt"
"$PYTHON_BIN" - "$JOBS_JSON" "$JOBS_TXT" "$OUT" "$EXECUTION_MODE" "$RUN_MODE" "${SUBMITTED_NAMES[@]}" -- "${SUBMITTED_IDS[@]}" <<'PY'
import json, sys
json_path, txt_path, out, mode, run_mode = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
args = sys.argv[6:]
idx = args.index("--")
names, ids = args[:idx], args[idx+1:]
jobs = [{"name": n, "job_id": i} for n, i in zip(names, ids)]
payload = {
    "output_dir": out,
    "execution_mode": mode,
    "run_mode": run_mode,
    "jobs": jobs,
    "note": "Downstream extract/merge IDs appended by orchestrators",
}
open(json_path, "w", encoding="utf-8").write(json.dumps(payload, indent=2) + "\n")
lines = [
    "Cementitious Materials / 7-30 results job summary (sharded)",
    f"output_dir={out}",
    f"execution_mode={mode}",
    f"run_mode={run_mode}",
    "",
]
lines.extend(f"{j['name']}: {j['job_id']}" for j in jobs)
open(txt_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY

echo
echo "Submitted job IDs written to:"
echo "  $JOBS_JSON"
echo "  $JOBS_TXT"
echo
echo "Monitor:"
echo "  squeue -u \"\$USER\""
if [[ ${#SUBMITTED_IDS[@]} -gt 0 ]]; then
  joined_ids=$(IFS=,; echo "${SUBMITTED_IDS[*]}")
  echo "  sacct -j ${joined_ids} --format=JobID,JobName,State,Elapsed,ExitCode"
fi
echo
[[ -n "$SCREEN_RANGE" ]] && echo "Screen array range: $SCREEN_RANGE"
[[ -n "$WEB_SEARCH_RANGE" ]] && echo "Web search array range: $WEB_SEARCH_RANGE"
echo "Expected final results directory: $OUT"
echo "Done. No git push performed."
exit 0
