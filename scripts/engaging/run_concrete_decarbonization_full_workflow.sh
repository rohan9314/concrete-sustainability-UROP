#!/bin/bash
# Canonical one-line Concrete Decarbonization Engaging launcher.
#
# After exporting OPENAI_API_KEY, TAVILY_API_KEY, and PICKLE_PATH
# (RESULTS_ROOT defaults to <repo>/results):
#
#   bash scripts/engaging/run_concrete_decarbonization_full_workflow.sh --full
#   bash scripts/engaging/run_concrete_decarbonization_full_workflow.sh --full --dry-run
#   bash scripts/engaging/run_concrete_decarbonization_full_workflow.sh --pilot-50
#   bash scripts/engaging/run_concrete_decarbonization_full_workflow.sh --pilot-1000
#   bash scripts/engaging/run_concrete_decarbonization_full_workflow.sh --smoke   # or --pilot
#
# Backward-compatible alias:
#   bash scripts/engaging/run_cementitious_full_workflow.sh --full
#
# Submits the full literature+web Slurm DAG through hierarchical export.
# Does not print secret values. Does not push. Does not call APIs during dry-run.
# Does not submit jobs when --dry-run is set.
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
    --pilot|--smoke|pilot|smoke) MODE="pilot" ;;
    --pilot-50|pilot-50|--pilot50) MODE="pilot-50" ;;
    --pilot-1000|pilot-1000|--pilot1000) MODE="pilot-1000" ;;
    --full|full) MODE="full" ;;
    --dry-run|dry-run) DRY_RUN=1 ;;
    --allow-uncalibrated-resources) ALLOW_UNCALIBRATED=1 ;;
    -h|--help)
      sed -n '1,20p' "$0"
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $arg" >&2
      echo "Usage: $0 --smoke|--pilot|--pilot-50|--pilot-1000|--full [--dry-run] [--allow-uncalibrated-resources]" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$MODE" ]]; then
  echo "ERROR: require --smoke, --pilot, --pilot-50, --pilot-1000, or --full" >&2
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
put("CFG_PILOT_TAXONOMY_SCOPE", cfg.get("pilot_taxonomy_scope") or "")
put("CFG_PILOT_CORPUS_SAMPLING", "1" if cfg.get("pilot_corpus_sampling") else "0")
for k, v in (cfg.get("web_limits") or {}).items():
    put(f"CFG_{k}", v)
put("CFG_LEAF_COUNT", tax.get("leaf_count", ""))
put("CFG_SUB_COUNT", tax.get("subcategory_count", ""))
put("CFG_WEB_LEAVES", ",".join(tax.get("web_leaves") or []))
put("CFG_WEB_SEARCH_SCOPE", tax.get("web_search_scope") or cfg.get("web_search_scope") or "")
put("CFG_WEB_SEARCH_NODE_COUNT", len(tax.get("web_search_nodes") or []))
put("CFG_WEB_SEARCH_L1", ",".join(sorted({n.get("level_1") for n in (tax.get("web_search_nodes") or []) if n.get("level_1")})))
put("CFG_RUN_MODE", cfg.get("run_mode") or "literature-and-web")
put("CFG_LITERATURE_ENABLED", "1" if cfg.get("literature_enabled", True) else "0")
put("CFG_WEB_ENABLED", "1" if cfg.get("web_enabled", True) else "0")
put("CFG_SAMPLE_SEED", "" if cfg.get("sample_seed") is None else cfg.get("sample_seed"))
put("CFG_RESULTS_SUFFIX", cfg.get("results_suffix") or "")
put("CFG_TELEMETRY", "1" if cfg.get("telemetry_enabled", True) else "0")
canon = tax.get("canonical") or {}
put("CFG_TAX_ROOT", canon.get("taxonomy_root") or "Concrete Decarbonization")
put("CFG_TAX_L0", canon.get("level_0_nodes", ""))
put("CFG_TAX_L1", canon.get("level_1_nodes", ""))
put("CFG_TAX_L2", canon.get("level_2_nodes", ""))
put("CFG_TAX_L3", canon.get("level_3_nodes", ""))
put("CFG_TAX_L4", canon.get("level_4_nodes", ""))
put("CFG_SEARCHABLE_WEB_NODES", canon.get("searchable_web_node_count", ""))
Path(sys.argv[2]).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
# shellcheck disable=SC1090
source "$ENV_FILE"
rm -f "$ENV_FILE"

echo
"$PYTHON_BIN" - "$REPORT_FILE" <<'PY'
import json
import os
import sys
from pathlib import Path
from pipeline.cementitious.workflow_launch import render_preflight_summary

report = json.loads(Path(sys.argv[1]).read_text())
print(render_preflight_summary(report, environ=dict(os.environ)))
PY
echo
if [[ -n "${CFG_SELECTED_SUBS}" || -n "${CFG_SELECTED_SS}" || "$MODE" == "pilot" ]]; then
  if [[ "$MODE" == "pilot" && -z "${CFG_SELECTED_SUBS}" && -z "${CFG_SELECTED_SS}" && "${CFG_PILOT_TAXONOMY_SCOPE:-}" == "all" ]]; then
    :
  else
    echo "WARNING: taxonomy restriction is ACTIVE (this is not the complete Concrete Decarbonization tree)."
    echo "  SELECTED_SUBCATEGORIES=${CFG_SELECTED_SUBS:-<none>}"
    echo "  SELECTED_SUB_SUBCATEGORIES=${CFG_SELECTED_SS:-<none>}"
    echo "  A user should abort now if they intended --full / --pilot-50 / --pilot-1000."
    echo
  fi
fi

export RESULTS_ROOT="$CFG_RESULTS_ROOT"
export PICKLE_PATH="$CFG_PICKLE"
export PAPER_RECORDS_PATH="$CFG_PICKLE"
export TAXONOMY_PATH="$CFG_TAXONOMY"
export SHARD_SIZE="$CFG_SHARD_SIZE"
export CEMENTITIOUS_WORKERS="$CFG_WORKERS"
export ARRAY_MAX_CONCURRENCY="$CFG_ARRAY_CONC"
export RUN_MODE="${CFG_RUN_MODE:-literature-and-web}"
export LITERATURE_ONLY=$([ "${CFG_LITERATURE_ENABLED:-1}" = "1" ] && [ "${CFG_WEB_ENABLED:-1}" != "1" ] && echo 1 || echo 0)
export WEB_ONLY=$([ "${CFG_WEB_ENABLED:-1}" = "1" ] && [ "${CFG_LITERATURE_ENABLED:-1}" != "1" ] && echo 1 || echo 0)
export WEB_SEARCH_ENABLED="${CFG_WEB_ENABLED:-1}"
export LITERATURE_ENABLED="${CFG_LITERATURE_ENABLED:-1}"
export WEB_SEARCH_SCOPE="${CFG_WEB_SEARCH_SCOPE}"
export SELECTED_SUBCATEGORIES="$CFG_SELECTED_SUBS"
export SELECTED_SUB_SUBCATEGORIES="$CFG_SELECTED_SS"
if [[ "$MODE" == "pilot" ]]; then
  export CEMENTITIOUS_PILOT_TAXONOMY_SCOPE="${CFG_PILOT_TAXONOMY_SCOPE:-smoke}"
elif [[ "$MODE" == "pilot-50" || "$MODE" == "pilot-1000" ]]; then
  export CEMENTITIOUS_PILOT_TAXONOMY_SCOPE="all"
fi
export WEB_QUERIES_PER_SUBCATEGORY="${CFG_WEB_QUERIES_PER_SUBCATEGORY}"
export WEB_QUERIES_PER_SUB_SUBCATEGORY="${CFG_WEB_QUERIES_PER_SUB_SUBCATEGORY}"
export WEB_RESULTS_PER_QUERY="${CFG_WEB_RESULTS_PER_QUERY}"
export WEB_MAX_URLS_PER_BRANCH="${CFG_WEB_MAX_URLS_PER_BRANCH}"
export WEB_MAX_TOTAL_URLS="${CFG_WEB_MAX_TOTAL_URLS}"
export WEB_LIMIT="${CFG_WEB_LIMIT}"
export WEB_SEARCH_SHARD_SIZE="${CFG_WEB_SEARCH_SHARD_SIZE}"
export WEB_EXTRACT_SHARD_SIZE="${CFG_WEB_EXTRACT_SHARD_SIZE}"
export WEB_MAX_TOTAL_QUERIES="${CFG_WEB_MAX_TOTAL_QUERIES:-}"
export WEB_RATE_LIMIT_SLEEP_S="${CFG_WEB_RATE_LIMIT_SLEEP_S:-}"
export WEB_QUERIES_PER_NODE="${CFG_WEB_QUERIES_PER_NODE:-}"
export WEB_CONCURRENCY="${CFG_WEB_CONCURRENCY:-}"
export CEMENTITIOUS_SAMPLE_SEED="${CFG_SAMPLE_SEED:-42}"
export SAMPLE_SEED="${CFG_SAMPLE_SEED:-42}"
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

if [[ "$MODE" == "full" ]]; then
  unset CEMENTITIOUS_MAX_RECORDS || true
else
  export CEMENTITIOUS_MAX_RECORDS="$CFG_MAX_RECORDS"
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
  echo "export.complete will appear at: $OUT/checkpoints/export.complete"
  echo "  (written only after hierarchical export AND validation pass)"
  echo "Intended stages + memory:"
  "$PYTHON_BIN" - <<PY
import json
from pathlib import Path
report = json.loads(Path(r"""$OUT/metadata/workflow_launch_plan.json""").read_text())
dry = report.get("dry_run") or {}
print("conceptual_dag:")
for i, stage in enumerate(dry.get("conceptual_dag") or [], 1):
    print(f"  {i:02d}. {stage}")
print("slurm_stage_order:")
for i, stage in enumerate(dry.get("stage_order") or [], 1):
    print(f"  {i:02d}. {stage}")
for name, info in (dry.get("resource_requests") or {}).items():
    print(f"  mem[{name}]={info.get('mem')} soft={info.get('soft_limit_gb')}G pickle={info.get('loads_full_pickle')}")
print("web_search_enabled:", dry.get("web_search_enabled"))
print("literature_enabled:", dry.get("literature_enabled"))
print("literature_record_cap:", dry.get("literature_record_cap"))
print("literature_record_cap_display:", dry.get("literature_record_cap_display"))
print("taxonomy_restriction:", dry.get("taxonomy_restriction"))
print("sample_seed:", dry.get("sample_seed"))
print("estimated_corpus_records:", dry.get("estimated_corpus_records"))
print("estimated_literature_shard_count:", dry.get("estimated_literature_shard_count"))
print("workers:", dry.get("workers"))
print("array_max_concurrency:", dry.get("array_max_concurrency"))
print("pilot_telemetry_source:", dry.get("pilot_telemetry_source"))
print("concurrency_memory_note:", dry.get("concurrency_memory_note"))
print("results_suffix:", dry.get("results_suffix"))
print("web_leaf_count:", dry.get("web_leaf_count"))
print("web_search_node_count:", dry.get("web_search_node_count"))
print("web_search_level_1_branches:", dry.get("web_search_level_1_branches"))
print("web_search_restricted_to_chemical_absorption:", dry.get("web_search_restricted_to_chemical_absorption"))
print("canonical_taxonomy:", dry.get("canonical_taxonomy"))
print("web_limits:", dry.get("web_limits"))
print("telemetry_enabled:", dry.get("telemetry_enabled"))
print("hierarchical_export:", dry.get("hierarchical_export"))
print("export_complete_path:", dry.get("export_complete_path"))
print("acyclic:", (dry.get("dependency_graph") or {}).get("acyclic"))
print("soft_fraction_of_slurm_mem:", dry.get("soft_fraction_of_slurm_mem"))
print("REPO_ROOT=" + r"""$REPO_ROOT""")
print("ENGAGING_SCRIPTS=" + r"""$ENGAGING_SCRIPTS""")
print("preprocess_sbatch:", f'--chdir={r"""$REPO_ROOT"""} --export=ALL,REPO_ROOT=... {r"""$ENGAGING_SCRIPTS"""}/730_cementitious_preprocess_plan.sh')
print("helper_resolve_out:", r"""$ENGAGING_SCRIPTS/_resolve_cementitious_out.sh""")
print("helper_diagnostics:", r"""$ENGAGING_SCRIPTS/_cementitious_slurm_diagnostics.sh""")
print("final_metadata:", "metadata/run_manifest.json + metadata/validation_report.json (export stage; export.complete after pass)")
print("submitted_jobs_would_be:", r"""$OUT/metadata/submitted_jobs.json""")
print("one_line_manifest_would_be:", r"""$OUT/metadata/one_line_submission_manifest.json""")
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
echo "  one_line_submission_manifest: $OUT/metadata/one_line_submission_manifest.json"
echo "  submitted_jobs.json (bootstrap appends downstream IDs): $OUT/metadata/submitted_jobs.json"
echo "  final export.complete (only after hierarchical export + validation pass):"
echo "    $OUT/checkpoints/export.complete"
echo
echo "Monitor:"
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
echo "Completion check (export.complete + any failed jobs + final CSV):"
echo "  test -f \"$OUT/checkpoints/export.complete\" && echo COMPLETE || echo INCOMPLETE"
echo "  ls \"$OUT/concrete_decarbonization_results/concrete_decarbonization.csv\""
echo "  python -c \"import json; from pathlib import Path; p=Path(r'''$OUT/metadata/submitted_jobs.json''');"
echo "jobs=(json.loads(p.read_text()).get('jobs') or []) if p.is_file() else [];"
echo "print('submitted_jobs', len(jobs))\""
echo
echo "Flags: OUT_OF_MEMORY / 137 / signal 9 = cgroup kill; MaxRSS>80% ReqMem = raise mem;"
echo "  soft_memory_stop = resumable; TIMEOUT/NODE_FAIL may be unrelated to RAM."
echo
echo "Expected final outputs under: $OUT"
echo "  concrete_decarbonization_results/concrete_decarbonization.csv"
echo "  concrete_decarbonization_results/cementitious_materials/"
echo "  concrete_decarbonization_results/aggregate_procurement/"
echo "  concrete_decarbonization_results/concrete_design/"
echo "  cementitious_materials_results/cementitious_materials_all_records.csv"
echo "  all_records/cementitious_materials_all_records.csv  (internal/compat copy)"
echo "  metadata/resource_usage_summary.json"
echo "  metadata/full_run_resource_recommendations.json"
echo "  checkpoints/export.complete"
