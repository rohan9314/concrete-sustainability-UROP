#!/bin/bash
# MIT Engaging — short finalize submitter for literature-and-web.
#
# Depends (via Slurm afterok) on literature + web orchestrators having exited
# after recording their terminal merge job IDs. This script:
#   1) reads those terminal job IDs
#   2) submits merge → dedupe → optional migrate → export with real afterok deps
#   3) exits immediately (no marker polling / no long-running wait)
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"
mkdir -p logs

: "${RESULTS_ROOT:?Set RESULTS_ROOT}"
# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
source "$_SCRIPT_DIR/_resolve_cementitious_out.sh"
resolve_cementitious_out || exit 1

COMMON_EXPORT="${COMMON_EXPORT:-ALL,REPO_ROOT=$REPO_ROOT,RESULTS_ROOT=$RESULTS_ROOT}"
for key in TAXONOMY_PATH CHECKPOINT_DIR RUN_MODE FORCE RESUME KEYWORD_ONLY \
           SELECTED_SUBCATEGORIES SELECTED_SUB_SUBCATEGORIES SKIP_QC CCS_MIGRATE_INPUT \
           OPENAI_API_KEY TAVILY_API_KEY PICKLE_PATH PAPER_RECORDS_PATH; do
  if [[ -n "${!key:-}" ]]; then
    COMMON_EXPORT+=",${key}=${!key}"
  fi
done

LIT_TERM_FILE="$OUT/metadata/literature_terminal_job_id.txt"
WEB_TERM_FILE="$OUT/metadata/web_terminal_job_id.txt"

[[ -f "$LIT_TERM_FILE" ]] || { echo "ERROR: missing $LIT_TERM_FILE" >&2; exit 1; }
[[ -f "$WEB_TERM_FILE" ]] || { echo "ERROR: missing $WEB_TERM_FILE" >&2; exit 1; }

LIT_TERM="$(tr -d '[:space:]' < "$LIT_TERM_FILE")"
WEB_TERM="$(tr -d '[:space:]' < "$WEB_TERM_FILE")"
LIT_TERM="${LIT_TERM%%_*}"
WEB_TERM="${WEB_TERM%%_*}"
[[ -n "$LIT_TERM" && -n "$WEB_TERM" ]] || {
  echo "ERROR: empty terminal job IDs (lit=$LIT_TERM web=$WEB_TERM)" >&2
  exit 1
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
    --cpus-per-task=1 \
    --mem="${SUBMIT_LOGIN_MEM:-16G}" \
    --export="$COMMON_EXPORT" \
    "$@" \
    --wrap="cd \"$REPO_ROOT\" && export CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB=\${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-12.8} && $cmd"
}

declare -a SUBMITTED_NAMES=()
declare -a SUBMITTED_IDS=()
declare -a PARENTS=()

record_job() {
  SUBMITTED_NAMES+=("$1")
  SUBMITTED_IDS+=("$2")
  PARENTS+=("$3")
  echo "Submitted $1 -> $2 (parents: $3)"
}

echo "Finalize-submit: lit_terminal=$LIT_TERM web_terminal=$WEB_TERM"
prev_dep=$(join_deps "$LIT_TERM" "$WEB_TERM")

merge_job=$(submit_login cm-merge-lit-web \
  "bash scripts/engaging/730_cementitious_merge_literature_web.sh" \
  --dependency="$prev_dep")
record_job merge_literature_web "$merge_job" "$LIT_TERM,$WEB_TERM"
prev_dep=$(join_deps "$merge_job")

dedupe_job=$(submit_login cm-dedupe-qc \
  "bash scripts/engaging/730_cementitious_dedupe_qc.sh" \
  --dependency="$prev_dep")
record_job dedupe_qc "$dedupe_job" "$merge_job"
prev_dep=$(join_deps "$dedupe_job")

if [[ -n "${CCS_MIGRATE_INPUT:-}" ]]; then
  mig_job=$(submit_login cm-migrate-ccs \
    "python -m pipeline.cementitious.cluster migrate-carbon-capture --input \"$CCS_MIGRATE_INPUT\" --output \"$OUT\"" \
    --dependency="$prev_dep")
  record_job migrate_ccs "$mig_job" "$dedupe_job"
  prev_dep=$(join_deps "$mig_job")
fi

export_job=$(submit_login cm-export \
  "FORCE=${FORCE:-0} bash scripts/engaging/730_cementitious_export.sh" \
  --dependency="$prev_dep")
record_job export "$export_job" "${prev_dep#afterok:}"

# Append to submitted_jobs metadata
JOBS_JSON="$OUT/metadata/submitted_jobs.json"
JOBS_TXT="$OUT/metadata/submitted_jobs.txt"
python - "$JOBS_JSON" "$JOBS_TXT" "$OUT" "$LIT_TERM" "$WEB_TERM" \
  "${SUBMITTED_NAMES[@]}" -- "${SUBMITTED_IDS[@]}" -- "${PARENTS[@]}" <<'PY'
import json, sys
from pathlib import Path
json_path, txt_path, out = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
lit_term, web_term = sys.argv[4], sys.argv[5]
args = sys.argv[6:]
i1 = args.index("--")
rest = args[i1+1:]
i2 = rest.index("--")
names = args[:i1]
ids = rest[:i2]
parents = rest[i2+1:]
jobs = []
for n, jid, par in zip(names, ids, parents):
    jobs.append({
        "name": n,
        "job_id": jid,
        "job_name": n,
        "stage": n,
        "branch": "combined",
        "dependency_type": "afterok",
        "parent_job_ids": [p for p in str(par).split(",") if p],
        "array_range": None,
        "submission_command": f"sbatch --dependency=afterok:... {n}",
        "expected_outputs": [],
        "log_path": f"logs/{n}-%j.out",
    })
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
payload["literature_terminal_job_id"] = lit_term
payload["web_terminal_job_id"] = web_term
payload["finalize_jobs"] = jobs
payload["jobs"] = existing
payload["finalization_strategy"] = "afterok_on_terminal_branch_jobs"
payload["note"] = "No long-running marker-poll finalizer; deps use real Slurm afterok"
json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
with txt_path.open("a", encoding="utf-8") as handle:
    handle.write("\n# combined finalize (afterok on terminal lit+web jobs)\n")
    handle.write(f"literature_terminal_job_id: {lit_term}\n")
    handle.write(f"web_terminal_job_id: {web_term}\n")
    for j in jobs:
        handle.write(f"{j['name']}: {j['job_id']} parents={','.join(j['parent_job_ids'])}\n")
print(json.dumps(jobs, indent=2))
PY

echo "Finalize-submit complete (no polling). Jobs chained with afterok."
echo "OUT=$OUT"
