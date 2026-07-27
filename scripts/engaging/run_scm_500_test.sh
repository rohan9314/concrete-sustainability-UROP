#!/bin/bash
# MIT Engaging / SLURM — self-contained 500-paper SCM seed-category test
#
# Covers ONLY the eight playbook SCM seed categories with literature + internet
# retrieval. Does NOT run open-ended discovery or carbon-capture.
#
# Launch (from repo root, after env is set):
#   mkdir -p logs
#   sbatch --export=ALL scripts/engaging/run_scm_500_test.sh
#
# Dry run (no API calls, no papers processed):
#   bash scripts/engaging/run_scm_500_test.sh --dry-run
#   # or:
#   sbatch --export=ALL,DRY_RUN=1 scripts/engaging/run_scm_500_test.sh
#
#SBATCH --job-name=scm-500-test
#SBATCH --nodes=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH --output=logs/scm-500-test-%j.out
#SBATCH --error=logs/scm-500-test-%j.err

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"

# Ensure Slurm-relative log directory exists when possible (must also exist at sbatch time).
mkdir -p logs
mkdir -p "outputs/7-27 SCM Test/logs"

echo "=== SCM 500-paper Engaging launcher ==="
echo "Repo root: $REPO_ROOT"
echo "Open-ended discovery: disabled"
echo "Seed-category extraction: enabled"
echo "Internet retrieval: enabled"
echo "Carbon-capture execution: disabled"
echo "Run label: 7/27 SCM Test"
echo "Output directory: $REPO_ROOT/outputs/7-27 SCM Test"

# Optional Engaging Python module (ignore if unavailable on login/compute image).
module load python/3.11 2>/dev/null || true

# Prefer repo virtualenv when present.
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
  elif [[ -x "$REPO_ROOT/venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_ROOT/venv/bin/python"
  else
    PYTHON_BIN="$(command -v python3 || command -v python || true)"
  fi
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: Python interpreter not found. Set PYTHON_BIN or create .venv" >&2
  exit 1
fi
echo "Python: $PYTHON_BIN"

# Corpus path
if [[ -z "${PICKLE_PATH:-}" && -n "${PAPER_RECORDS_PATH:-}" ]]; then
  export PICKLE_PATH="$PAPER_RECORDS_PATH"
fi
: "${PICKLE_PATH:?Set PICKLE_PATH to the absolute corpus pickle path}"
if [[ ! -f "$PICKLE_PATH" ]]; then
  echo "ERROR: PICKLE_PATH does not exist: $PICKLE_PATH" >&2
  exit 1
fi
export PICKLE_PATH
export PAPER_RECORDS_PATH="${PAPER_RECORDS_PATH:-$PICKLE_PATH}"

# API keys (never print values)
: "${OPENAI_API_KEY:?Set OPENAI_API_KEY}"
: "${TAVILY_API_KEY:?Set TAVILY_API_KEY}"
if [[ "$TAVILY_API_KEY" == "YOUR_TAVILY_TOKEN_HERE" ]]; then
  echo "ERROR: TAVILY_API_KEY is still the placeholder value" >&2
  exit 1
fi
echo "OPENAI_API_KEY: set"
echo "TAVILY_API_KEY: set"

export OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/outputs}"
export SCM_OUTPUT_ROOT="${SCM_OUTPUT_ROOT:-$OUTPUT_DIR/7-27 SCM Test}"
export EXTRACTION_CONCURRENCY="${EXTRACTION_CONCURRENCY:-2}"

# Refuse carbon-capture collision
CC_ROOT="${CARBON_CAPTURE_OUTPUT_ROOT:-$OUTPUT_DIR/carbon_capture}"
if [[ "$(cd "$SCM_OUTPUT_ROOT" 2>/dev/null && pwd -P || echo "$SCM_OUTPUT_ROOT")" == "$(cd "$CC_ROOT" 2>/dev/null && pwd -P || echo "$CC_ROOT")" ]]; then
  echo "ERROR: SCM_OUTPUT_ROOT equals carbon-capture output root" >&2
  exit 1
fi
case "$SCM_OUTPUT_ROOT" in
  *carbon_capture*)
    echo "ERROR: SCM_OUTPUT_ROOT must not contain carbon_capture: $SCM_OUTPUT_ROOT" >&2
    exit 1
    ;;
esac

echo "OUTPUT_DIR=$OUTPUT_DIR"
echo "SCM_OUTPUT_ROOT=$SCM_OUTPUT_ROOT"
echo "EXTRACTION_CONCURRENCY=$EXTRACTION_CONCURRENCY"
echo "PICKLE_PATH=$PICKLE_PATH"

DRY_ARGS=()
if [[ "${1:-}" == "--dry-run" || "${DRY_RUN:-}" == "1" || "${DRY_RUN:-}" == "true" ]]; then
  DRY_ARGS+=(--dry-run)
  export DRY_RUN=1
  echo "Mode: DRY RUN"
else
  echo "Mode: FULL RUN (literature + web for eight seed categories)"
fi

# Single orchestration entry — no nested sbatch, no discovery, no carbon capture.
exec "$PYTHON_BIN" "$REPO_ROOT/scripts/engaging/run_scm_500_test.py" "${DRY_ARGS[@]}"
