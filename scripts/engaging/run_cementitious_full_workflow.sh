#!/bin/bash
# One-line Cementitious Materials Engaging launcher (pilot or full).
#
# After exporting OPENAI_API_KEY, TAVILY_API_KEY, PICKLE_PATH, RESULTS_ROOT:
#   bash scripts/engaging/run_cementitious_full_workflow.sh --pilot
#   bash scripts/engaging/run_cementitious_full_workflow.sh --full
#   bash scripts/engaging/run_cementitious_full_workflow.sh --pilot --dry-run
#   bash scripts/engaging/run_cementitious_full_workflow.sh --full --dry-run
#
# Submits the full literature+web dependency chain through final CSV/citation export.
# Does not print secret values. Does not push. Does not call APIs during dry-run.
set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }

# Login-node launcher: prefer git toplevel, then validated REPO_ROOT / submit dir.
# Do not trust Slurm spool paths for repository helpers.
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
cementitious_resolve_repo_root "one_line_launcher" || exit 1
cd "$REPO_ROOT"
export REPO_ROOT
mkdir -p logs
ENGAGING_SCRIPTS="$REPO_ROOT/scripts/engaging"

MODE=""
DRY_RUN=0
ALLOW_UNCALIBRATED=0
for arg in "$@"; do
  case "$arg" in
    --pilot|pilot) MODE="pilot" ;;
    --full|full) MODE="full" ;;
    --dry-run|dry-run) DRY_RUN=1 ;;
    --allow-uncalibrated-resources) ALLOW_UNCALIBRATED=1 ;;
    -h|--help)
      sed -n '1,20p' "$0"
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $arg" >&2
      echo "Usage: $0 --pilot|--full [--dry-run] [--allow-uncalibrated-resources]" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$MODE" ]]; then
  echo "ERROR: require --pilot or --full" >&2
  exit 1
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

if [[ -z "${PICKLE_PATH:-}" && -n "${PAPER_RECORDS_PATH:-}" ]]; then
  export PICKLE_PATH="$PAPER_RECORDS_PATH"
fi
if [[ -n "${PICKLE_PATH:-}" && -z "${PAPER_RECORDS_PATH:-}" ]]; then
  export PAPER_RECORDS_PATH="$PICKLE_PATH"
fi

LAUNCH_ARGS=(--mode "$MODE" --json)
if [[ "$DRY_RUN" == "1" ]]; then
  LAUNCH_ARGS+=(--dry-run)
fi
if [[ "$ALLOW_UNCALIBRATED" == "1" ]]; then
  LAUNCH_ARGS+=(--allow-uncalibrated-resources)
  export ALLOW_UNCALIBRATED_RESOURCES=1
fi

REPORT_FILE="$(mktemp)"
trap 'rm -f "$REPORT_FILE"' EXIT
set +e
"$PYTHON_BIN" -m pipeline.cementitious.workflow_launch "${LAUNCH_ARGS[@]}" >"$REPORT_FILE"
PRE_RC=$?
set -e

if [[ ! -s "$REPORT_FILE" ]]; then
  die "workflow preflight produced no output"
fi
if [[ "$PRE_RC" -ne 0 ]]; then
  echo "Preflight failed:" >&2
  "$PYTHON_BIN" - "$REPORT_FILE" <<'PY' >&2
import json, sys
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_text())
for err in report.get("errors") or []:
    print(f"  - {err}")
if not report.get("errors"):
    print(Path(sys.argv[1]).read_text()[:2000])
PY
  exit 1
fi

ENV_FILE="$(mktemp)"
"$PYTHON_BIN" - "$REPORT_FILE" "$ENV_FILE" <<'PY'
import json, shlex, sys
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_text())
cfg = report["config"]
tax = report.get("taxonomy") or {}
lines = []
def put(key, value):
    lines.append(f"{key}={shlex.quote('' if value is None else str(value))}")
put("CFG_RESULTS_ROOT", cfg["results_root"])
put("CFG_OUTPUT_DIR", cfg["output_dir"])
put("CFG_PICKLE", cfg["pickle_path"])
put("CFG_TAXONOMY", cfg["taxonomy_path"])
put("CFG_MAX_RECORDS", "" if cfg.get("max_records") is None else cfg.get("max_records"))
put("CFG_SHARD_SIZE", cfg["shard_size"])
put("CFG_WORKERS", cfg["workers"])
put("CFG_ARRAY_CONC", cfg["array_max_concurrency"])
put("CFG_SELECTED_SUBS", ",".join(cfg.get("selected_subcategories") or []))
put("CFG_SELECTED_SS", ",".join(cfg.get("selected_sub_subcategories") or []))
for k, v in (cfg.get("web_limits") or {}).items():
    put(f"CFG_{k}", v)
put("CFG_LEAF_COUNT", tax.get("leaf_count", ""))
put("CFG_SUB_COUNT", tax.get("subcategory_count", ""))
put("CFG_WEB_LEAVES", ",".join(tax.get("web_leaves") or []))
Path(sys.argv[2]).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
# shellcheck disable=SC1090
source "$ENV_FILE"
rm -f "$ENV_FILE"

  echo "======== Cementitious one-line workflow ========"
echo "mode=$MODE"
echo "dry_run=$DRY_RUN"
echo "run_mode=literature-and-web"
echo "literature_enabled=yes"
echo "web_search_enabled=yes (Tavily)"
echo "REPO_ROOT=$REPO_ROOT"
echo "ENGAGING_SCRIPTS=$ENGAGING_SCRIPTS"
if [[ -n "${CFG_MAX_RECORDS}" ]]; then
  echo "literature_record_cap=$CFG_MAX_RECORDS"
else
  echo "literature_record_cap=FULL"
fi
echo "RESULTS_ROOT=$CFG_RESULTS_ROOT"
echo "OUT=$CFG_OUTPUT_DIR"
echo "PICKLE_PATH=$CFG_PICKLE"
echo "TAXONOMY_PATH=$CFG_TAXONOMY"
echo "subcategories=$CFG_SUB_COUNT taxonomy_leaves=$CFG_LEAF_COUNT"
echo "web_leaf_slugs=$CFG_WEB_LEAVES"
echo "web_leaf_manifest=$CFG_OUTPUT_DIR/metadata/workflow_launch_plan.json"
echo "shard_size=$CFG_SHARD_SIZE workers=$CFG_WORKERS array_concurrency=$CFG_ARRAY_CONC"
echo "SELECTED_SUBCATEGORIES=${CFG_SELECTED_SUBS:-<all>}"
echo "SELECTED_SUB_SUBCATEGORIES=${CFG_SELECTED_SS:-<all>}"
echo "OPENAI_API_KEY: $([ -n "${OPENAI_API_KEY:-}" ] && echo set || echo unset)"
echo "TAVILY_API_KEY: $([ -n "${TAVILY_API_KEY:-}" ] && echo set || echo unset)"
echo "================================================"

export RESULTS_ROOT="$CFG_RESULTS_ROOT"
export PICKLE_PATH="$CFG_PICKLE"
export PAPER_RECORDS_PATH="$CFG_PICKLE"
export TAXONOMY_PATH="$CFG_TAXONOMY"
export SHARD_SIZE="$CFG_SHARD_SIZE"
export CEMENTITIOUS_WORKERS="$CFG_WORKERS"
export ARRAY_MAX_CONCURRENCY="$CFG_ARRAY_CONC"
export RUN_MODE="literature-and-web"
export LITERATURE_ONLY=0
export WEB_ONLY=0
export SELECTED_SUBCATEGORIES="$CFG_SELECTED_SUBS"
export SELECTED_SUB_SUBCATEGORIES="$CFG_SELECTED_SS"
export WEB_QUERIES_PER_SUBCATEGORY="${CFG_WEB_QUERIES_PER_SUBCATEGORY}"
export WEB_QUERIES_PER_SUB_SUBCATEGORY="${CFG_WEB_QUERIES_PER_SUB_SUBCATEGORY}"
export WEB_RESULTS_PER_QUERY="${CFG_WEB_RESULTS_PER_QUERY}"
export WEB_MAX_URLS_PER_BRANCH="${CFG_WEB_MAX_URLS_PER_BRANCH}"
export WEB_MAX_TOTAL_URLS="${CFG_WEB_MAX_TOTAL_URLS}"
export WEB_LIMIT="${CFG_WEB_LIMIT}"
export WEB_SEARCH_SHARD_SIZE="${CFG_WEB_SEARCH_SHARD_SIZE}"
export WEB_EXTRACT_SHARD_SIZE="${CFG_WEB_EXTRACT_SHARD_SIZE}"
export CEMENTITIOUS_BATCH_SIZE="${CEMENTITIOUS_BATCH_SIZE:-25}"
export CEMENTITIOUS_MAX_IN_FLIGHT="${CEMENTITIOUS_MAX_IN_FLIGHT:-1}"
export CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB="${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-6.4}"
export TOP_N="${TOP_N:-${TOP_N_SOURCES:-50}}"
export EXTRACT_SHARD_SIZE="${EXTRACT_SHARD_SIZE:-25}"
export RESUME="${RESUME:-0}"
export FORCE="${FORCE:-0}"
export KEYWORD_ONLY="${KEYWORD_ONLY:-0}"
export WORKFLOW_MODE="$MODE"
export SUBMIT_LOGIN_MEM="${SUBMIT_LOGIN_MEM:-16G}"

# If full mode and calibration exists, apply recommended mem env (no secrets).
# Deferred until OUT exists below.

if [[ "$MODE" == "pilot" ]]; then
  export CEMENTITIOUS_MAX_RECORDS="$CFG_MAX_RECORDS"
else
  unset CEMENTITIOUS_MAX_RECORDS || true
fi

# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
cementitious_source_engaging_helper "_resolve_cementitious_out.sh" "one_line_launcher" || exit 1
resolve_cementitious_out || exit 1
mkdir -p "$OUT/metadata" "$OUT/logs" "$OUT/checkpoints"
printf '%s\n' "$REPO_ROOT" >"$OUT/metadata/repo_root.txt"
"$PYTHON_BIN" - <<PY
from pathlib import Path
import json
from datetime import datetime, timezone
meta = Path(r"""$OUT""") / "metadata" / "repo_root.json"
meta.write_text(
    json.dumps(
        {
            "repo_root": r"""$REPO_ROOT""",
            "engaging_scripts": r"""$ENGAGING_SCRIPTS""",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "secrets_included": False,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(f"Wrote {meta}")
PY

if [[ "$MODE" == "full" && "$ALLOW_UNCALIBRATED" != "1" ]]; then
  CAL_ENV="$OUT/metadata/applied_full_run_resources.env"
  "$PYTHON_BIN" - "$CAL_ENV" <<'PY' || true
import json, os, sys
from pathlib import Path
from pipeline.cementitious.resource_calibration import (
    apply_recommendations_to_environ,
    resolve_pilot_output_for_calibration,
)
out_env = Path(sys.argv[1])
pilot = resolve_pilot_output_for_calibration(results_root=os.getenv("RESULTS_ROOT"))
if not pilot:
    raise SystemExit(0)
reco = Path(pilot) / "metadata" / "full_run_resource_recommendations.json"
if not reco.is_file():
    raise SystemExit(0)
payload = json.loads(reco.read_text())
env = apply_recommendations_to_environ(payload)
lines = []
for k, v in env.items():
    if k.startswith("CEMENTITIOUS_MEM_") or k.startswith("CEMENTITIOUS_SOFT_") or k in {
        "SUBMIT_LOGIN_MEM", "CEMENTITIOUS_WORKERS", "ARRAY_MAX_CONCURRENCY"
    }:
        lines.append(f"export {k}={v!r}")
out_env.parent.mkdir(parents=True, exist_ok=True)
out_env.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Wrote calibrated resource env -> {out_env}")
PY
  if [[ -f "$CAL_ENV" ]]; then
    # shellcheck disable=SC1090
    source "$CAL_ENV"
    echo "Applied pilot-calibrated Slurm memory recommendations."
  fi
fi

cp "$REPORT_FILE" "$OUT/metadata/workflow_launch_plan.json"

if [[ "$DRY_RUN" == "1" ]]; then
  echo
  echo "DRY-RUN complete — no sbatch, no OpenAI, no Tavily, no full pickle load."
  echo "Plan written to: $OUT/metadata/workflow_launch_plan.json"
  echo "Intended stages + memory:"
  "$PYTHON_BIN" - <<PY
import json
from pathlib import Path
report = json.loads(Path(r"""$OUT/metadata/workflow_launch_plan.json""").read_text())
dry = report.get("dry_run") or {}
for i, stage in enumerate(dry.get("stage_order") or [], 1):
    print(f"  {i:02d}. {stage}")
for name, info in (dry.get("resource_requests") or {}).items():
    print(f"  mem[{name}]={info.get('mem')} soft={info.get('soft_limit_gb')}G pickle={info.get('loads_full_pickle')}")
print("web_search_enabled:", dry.get("web_search_enabled"))
print("literature_record_cap:", dry.get("literature_record_cap"))
print("web_leaf_count:", dry.get("web_leaf_count"))
print("acyclic:", (dry.get("dependency_graph") or {}).get("acyclic"))
print("soft_fraction_of_slurm_mem:", dry.get("soft_fraction_of_slurm_mem"))
print("REPO_ROOT:", r"""$REPO_ROOT""")
print("ENGAGING_SCRIPTS:", r"""$ENGAGING_SCRIPTS""")
print("preprocess_sbatch:", f'--chdir={r"""$REPO_ROOT"""} --export=ALL,REPO_ROOT=... {r"""$ENGAGING_SCRIPTS"""}/730_cementitious_preprocess_plan.sh')
print("helper_resolve_out:", r"""$ENGAGING_SCRIPTS/_resolve_cementitious_out.sh""")
print("helper_diagnostics:", r"""$ENGAGING_SCRIPTS/_cementitious_slurm_diagnostics.sh""")
PY
  exit 0
fi

command -v sbatch >/dev/null 2>&1 || die "sbatch not found — run on an Engaging login node"

PREPROCESS_JOB=$(sbatch --parsable \
  --chdir="$REPO_ROOT" \
  --export=ALL,REPO_ROOT="$REPO_ROOT" \
  "$ENGAGING_SCRIPTS/730_cementitious_preprocess_plan.sh")
echo "Submitted preprocess_plan -> $PREPROCESS_JOB"

BOOTSTRAP_JOB=$(sbatch --parsable \
  --chdir="$REPO_ROOT" \
  --job-name="cm-bootstrap-${MODE}" \
  --output="logs/cm-bootstrap-${MODE}-%j.out" \
  --error="logs/cm-bootstrap-${MODE}-%j.err" \
  --time=02:00:00 \
  --cpus-per-task=1 \
  --mem=8G \
  --dependency="afterok:${PREPROCESS_JOB}" \
  --export=ALL,REPO_ROOT="$REPO_ROOT",SKIP_LIT_PLAN=1,DRY_RUN=0,EXECUTION_MODE=submit,RUN_MODE=literature-and-web \
  --wrap="cd \"$REPO_ROOT\" && export REPO_ROOT=\"$REPO_ROOT\" && bash \"$ENGAGING_SCRIPTS/run_730_results.sh\"")
echo "Submitted bootstrap (screen/web/finalize chain) -> $BOOTSTRAP_JOB"

"$PYTHON_BIN" - <<PY
import json
from pathlib import Path
from datetime import datetime, timezone
out = Path(r"""$OUT""")
cap = r"""$CFG_MAX_RECORDS"""
payload = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "workflow_mode": r"""$MODE""",
    "run_mode": "literature-and-web",
    "web_search_enabled": True,
    "literature_record_cap": cap if cap else "FULL",
    "repo_root": r"""$REPO_ROOT""",
    "engaging_scripts": r"""$ENGAGING_SCRIPTS""",
    "chdir": r"""$REPO_ROOT""",
    "preprocess_script": r"""$ENGAGING_SCRIPTS/730_cementitious_preprocess_plan.sh""",
    "results_root": r"""$RESULTS_ROOT""",
    "output_dir": str(out),
    "jobs": [
        {"name": "preprocess_plan", "job_id": r"""$PREPROCESS_JOB"""},
        {
            "name": "bootstrap_full_chain",
            "job_id": r"""$BOOTSTRAP_JOB""",
            "depends_on": [r"""$PREPROCESS_JOB"""],
        },
    ],
    "final_bootstrap_job_id": r"""$BOOTSTRAP_JOB""",
    "note": (
        "Bootstrap submits screen/web arrays + orchestrators + finalize; "
        "terminal export job ID is appended to submitted_jobs.json by finalize."
    ),
    "secrets_included": False,
}
path = out / "metadata" / "one_line_submission_manifest.json"
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {path}")
PY

echo
echo "Submitted one-line $MODE workflow."
echo "  preprocess_job: $PREPROCESS_JOB"
echo "  bootstrap_job (submits remaining DAG): $BOOTSTRAP_JOB"
echo "  final export job ID will appear in: $OUT/metadata/submitted_jobs.json after finalize"
echo
echo "Monitor / memory accounting:"
echo "  squeue -u \"\$USER\""
echo "  sacct -j ${PREPROCESS_JOB},${BOOTSTRAP_JOB} --format=JobID,JobName,State,ExitCode,Elapsed,ReqMem,MaxRSS,MaxVMSize,AllocCPUS,NodeList"
echo "  seff ${PREPROCESS_JOB}"
echo "  seff ${BOOTSTRAP_JOB}"
echo "  # Inspect every job ID in manifests:"
echo "  python -c \"import json; from pathlib import Path; ids=[];\
\
for name in ('one_line_submission_manifest.json','submitted_jobs.json'):\
\
 p=Path(r'''$OUT/metadata''')/name;\
\
\
 ids+=[j.get('job_id') for j in (json.loads(p.read_text()).get('jobs') or [])] if p.is_file() else [];\
\
 print('sacct -j ' + ','.join(dict.fromkeys([i for i in ids if i])) + ' --format=JobID,JobName,State,ExitCode,Elapsed,ReqMem,MaxRSS,MaxVMSize,AllocCPUS,NodeList')\""
echo
echo "Flags: OUT_OF_MEMORY / 137 / signal 9 = cgroup kill; MaxRSS>80% ReqMem = raise mem;"
echo "  soft_memory_stop = resumable; TIMEOUT/NODE_FAIL may be unrelated to RAM."
echo
echo "Expected final outputs under: $OUT"
echo "  all_records/cementitious_materials_all_records.csv"
echo "  metadata/resource_usage_summary.json"
echo "  metadata/full_run_resource_recommendations.json"
