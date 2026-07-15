#!/bin/bash
# MIT Engaging — submit the full carbon capture pipeline as a dependent SLURM chain.
#
# Usage (on Engaging login node):
#   cd /home/rohan931/urop/concrete-sustainability-UROP
#   export OPENAI_API_KEY=...
#   export TAVILY_API_KEY=...
#   bash scripts/engaging/run_full_pipeline.sh
#
# Optional:
#   SKIP_SCREEN=1   reuse existing screening_merged.jsonl
#   SKIP_WEB=1      literature-only export (no Tavily)
#   START_FROM=N    start at stage N (1–8); earlier outputs must already exist
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"

export REPO_ROOT
export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
export PICKLE_PATH="${PICKLE_PATH:-$REPO_ROOT/filtered_records_rohan.pkl}"
export EXTRACTION_CONCURRENCY="${EXTRACTION_CONCURRENCY:-4}"
export TOP_N_SOURCES="${TOP_N_SOURCES:-50}"
export WEB_LIMIT="${WEB_LIMIT:-50}"
export SHARD_SIZE="${SHARD_SIZE:-10000}"

SKIP_SCREEN="${SKIP_SCREEN:-0}"
SKIP_WEB="${SKIP_WEB:-0}"
START_FROM="${START_FROM:-1}"

METHODS=(
  amine_absorption
  membrane_separation
  calcium_looping
  oxyfuel_combustion
  cryogenic_capture
  mineralization
)

mkdir -p logs "$OUTPUT_DIR"

if [[ -z "${OPENAI_API_KEY:-}" && "$START_FROM" -le 5 ]]; then
  echo "ERROR: OPENAI_API_KEY is required (screen/extract/web stages)." >&2
  exit 1
fi
if [[ "$SKIP_WEB" != "1" && -z "${TAVILY_API_KEY:-}" && "$START_FROM" -le 7 ]]; then
  echo "ERROR: TAVILY_API_KEY is required for web search. Set SKIP_WEB=1 to skip." >&2
  exit 1
fi

COMMON_EXPORT="ALL,REPO_ROOT=$REPO_ROOT,OUTPUT_DIR=$OUTPUT_DIR,PICKLE_PATH=$PICKLE_PATH"
COMMON_EXPORT+=",EXTRACTION_CONCURRENCY=$EXTRACTION_CONCURRENCY,TOP_N_SOURCES=$TOP_N_SOURCES"
COMMON_EXPORT+=",WEB_LIMIT=$WEB_LIMIT,SHARD_SIZE=$SHARD_SIZE"
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  COMMON_EXPORT+=",OPENAI_API_KEY=$OPENAI_API_KEY"
fi
if [[ -n "${TAVILY_API_KEY:-}" ]]; then
  COMMON_EXPORT+=",TAVILY_API_KEY=$TAVILY_API_KEY"
fi

submit() {
  # submit <script> [extra sbatch args...]
  # Optional: first arg EXPORT_OVERRIDE=... to replace default --export.
  local script="$1"
  shift
  local export_flag="$COMMON_EXPORT"
  if [[ "${1:-}" == EXPORT_OVERRIDE=* ]]; then
    export_flag="${1#EXPORT_OVERRIDE=}"
    shift
  fi
  sbatch --parsable --export="$export_flag" "$@" "$script"
}

submit_login() {
  # Wrap a login-node bash script as a short SLURM job so dependencies work.
  local job_name="$1"
  local cmd="$2"
  shift 2
  sbatch --parsable \
    --job-name="$job_name" \
    --output="logs/${job_name}-%j.out" \
    --time=01:00:00 \
    --cpus-per-task=2 \
    --mem=8G \
    --export="$COMMON_EXPORT" \
    "$@" \
    --wrap="cd \"$REPO_ROOT\" && $cmd"
}

join_deps() {
  # join_deps jobid [jobid...] -> afterok:A:B:C
  local first=1
  local out="afterok"
  for id in "$@"; do
    [[ -z "$id" ]] && continue
    # Array jobs come back as 12345_0 or 12345; dependency needs base ID.
    id="${id%%_*}"
    if [[ "$first" -eq 1 ]]; then
      out="afterok:${id}"
      first=0
    else
      out="${out}:${id}"
    fi
  done
  if [[ "$first" -eq 1 ]]; then
    echo ""
  else
    echo "$out"
  fi
}

echo "REPO_ROOT=$REPO_ROOT"
echo "OUTPUT_DIR=$OUTPUT_DIR"
echo "PICKLE_PATH=$PICKLE_PATH"
echo "START_FROM=$START_FROM SKIP_SCREEN=$SKIP_SCREEN SKIP_WEB=$SKIP_WEB"
echo

prev_dep=""
declare -a stage_jobs=()

# ── 1. Screen ──────────────────────────────────────────────
if [[ "$START_FROM" -le 1 && "$SKIP_SCREEN" != "1" ]]; then
  screen_job=$(submit "$SCRIPT_DIR/01_screen_array.sh")
  echo "1 screen       -> $screen_job"
  prev_dep=$(join_deps "$screen_job")
else
  echo "1 screen       -> skipped"
fi

# ── 2. Merge screening ─────────────────────────────────────
if [[ "$START_FROM" -le 2 && "$SKIP_SCREEN" != "1" ]]; then
  dep_args=()
  [[ -n "$prev_dep" ]] && dep_args=(--dependency="$prev_dep")
  merge_screen_job=$(submit_login ccs-merge-screen \
    "bash scripts/engaging/02_merge_screening.sh" \
    "${dep_args[@]}")
  echo "2 merge-screen -> $merge_screen_job"
  prev_dep=$(join_deps "$merge_screen_job")
else
  echo "2 merge-screen -> skipped"
fi

# ── 3. Retrieve (×6) ───────────────────────────────────────
declare -a retrieve_jobs=()
if [[ "$START_FROM" -le 3 ]]; then
  dep_args=()
  [[ -n "$prev_dep" ]] && dep_args=(--dependency="$prev_dep")
  for m in "${METHODS[@]}"; do
    job=$(submit "$SCRIPT_DIR/03_retrieve_array.sh" \
      "EXPORT_OVERRIDE=${COMMON_EXPORT},METHODOLOGY=$m" \
      "${dep_args[@]}")
    retrieve_jobs+=("$job")
    echo "3 retrieve     -> $job ($m)"
  done
  prev_dep=$(join_deps "${retrieve_jobs[@]}")
else
  echo "3 retrieve     -> skipped"
fi

# ── 4. Merge-rank (×6) ─────────────────────────────────────
declare -a merge_rank_jobs=()
if [[ "$START_FROM" -le 4 ]]; then
  dep_args=()
  [[ -n "$prev_dep" ]] && dep_args=(--dependency="$prev_dep")
  for m in "${METHODS[@]}"; do
    job=$(submit_login "ccs-merge-rank-$m" \
      "METHODOLOGY=$m bash scripts/engaging/04_merge_rank.sh" \
      "${dep_args[@]}")
    merge_rank_jobs+=("$job")
    echo "4 merge-rank   -> $job ($m)"
  done
  prev_dep=$(join_deps "${merge_rank_jobs[@]}")
else
  echo "4 merge-rank   -> skipped"
fi

# ── 5. Extract literature (×6) ─────────────────────────────
declare -a extract_jobs=()
if [[ "$START_FROM" -le 5 ]]; then
  dep_args=()
  [[ -n "$prev_dep" ]] && dep_args=(--dependency="$prev_dep")
  for m in "${METHODS[@]}"; do
    job=$(submit "$SCRIPT_DIR/05_extract_array.sh" \
      "EXPORT_OVERRIDE=${COMMON_EXPORT},METHODOLOGY=$m" \
      "${dep_args[@]}")
    extract_jobs+=("$job")
    echo "5 extract      -> $job ($m)"
  done
  prev_dep=$(join_deps "${extract_jobs[@]}")
else
  echo "5 extract      -> skipped"
fi

# ── 6. Merge extract (×6) ──────────────────────────────────
declare -a merge_extract_jobs=()
if [[ "$START_FROM" -le 6 ]]; then
  dep_args=()
  [[ -n "$prev_dep" ]] && dep_args=(--dependency="$prev_dep")
  for m in "${METHODS[@]}"; do
    job=$(submit_login "ccs-merge-extract-$m" \
      "METHODOLOGY=$m bash scripts/engaging/06_merge_extract.sh" \
      "${dep_args[@]}")
    merge_extract_jobs+=("$job")
    echo "6 merge-extract-> $job ($m)"
  done
  prev_dep=$(join_deps "${merge_extract_jobs[@]}")
else
  echo "6 merge-extract-> skipped"
fi

# ── 7. Web (×6) ────────────────────────────────────────────
declare -a web_jobs=()
if [[ "$START_FROM" -le 7 && "$SKIP_WEB" != "1" ]]; then
  dep_args=()
  [[ -n "$prev_dep" ]] && dep_args=(--dependency="$prev_dep")
  for m in "${METHODS[@]}"; do
    job=$(submit "$SCRIPT_DIR/07_web_extract.sh" \
      "EXPORT_OVERRIDE=${COMMON_EXPORT},METHODOLOGY=$m" \
      "${dep_args[@]}")
    web_jobs+=("$job")
    echo "7 web          -> $job ($m)"
  done
  prev_dep=$(join_deps "${web_jobs[@]}")
else
  echo "7 web          -> skipped"
fi

# ── 8. Export CSV (×6) ─────────────────────────────────────
if [[ "$START_FROM" -le 8 ]]; then
  dep_args=()
  [[ -n "$prev_dep" ]] && dep_args=(--dependency="$prev_dep")
  for m in "${METHODS[@]}"; do
    job=$(submit_login "ccs-export-$m" \
      "METHODOLOGY=$m bash scripts/engaging/08_export_csv.sh" \
      "${dep_args[@]}")
    echo "8 export       -> $job ($m)"
  done
else
  echo "8 export       -> skipped"
fi

echo
echo "Full pipeline submitted."
echo "Monitor with:  squeue -u \$USER"
echo "CSVs will land in: $OUTPUT_DIR/carbon_capture/csv/"
echo "Logs: $REPO_ROOT/logs/"
