#!/bin/bash
# Shared repository-root resolution for Cementitious Materials Engaging jobs.
#
# Slurm may copy #SBATCH scripts into /var/spool/slurmd/job.../slurm_script.
# Never locate the repository from BASH_SOURCE[0] / dirname "$0" inside those jobs.
#
# Precedence:
#   1. REPO_ROOT when set and valid
#   2. SLURM_SUBMIT_DIR when it contains the expected repository structure
#   3. fail with a clear error (never silently use the Slurm spool directory)
#
# shellcheck shell=bash

cementitious_is_valid_repo_root() {
  local root="${1:-}"
  root="${root%/}"
  [[ -n "$root" && -d "$root" ]] || return 1
  # Refuse Slurm spool paths explicitly.
  case "$root" in
    */var/spool/slurmd/*|/var/spool/slurmd/*)
      return 1
      ;;
  esac
  [[ -f "$root/pipeline/cementitious/__init__.py" ]] || return 1
  [[ -f "$root/scripts/engaging/_resolve_cementitious_out.sh" ]] || return 1
  [[ -f "$root/scripts/engaging/_cementitious_slurm_diagnostics.sh" ]] || return 1
  [[ -f "$root/scripts/engaging/run_cementitious_full_workflow.sh" ]] || return 1
  return 0
}

cementitious_resolve_repo_root() {
  local stage="${1:-unknown}"
  local candidate=""

  if [[ -n "${REPO_ROOT:-}" ]]; then
    if cementitious_is_valid_repo_root "$REPO_ROOT"; then
      REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
      export REPO_ROOT
      export CEMENTITIOUS_ENGAGING_DIR="$REPO_ROOT/scripts/engaging"
      return 0
    fi
    echo "ERROR: REPO_ROOT is set but is not a valid Cementitious repository root (stage=$stage)." >&2
    echo "ERROR: attempted REPO_ROOT=$REPO_ROOT" >&2
  fi

  if [[ -n "${SLURM_SUBMIT_DIR:-}" ]]; then
    if cementitious_is_valid_repo_root "$SLURM_SUBMIT_DIR"; then
      REPO_ROOT="$(cd "$SLURM_SUBMIT_DIR" && pwd)"
      export REPO_ROOT
      export CEMENTITIOUS_ENGAGING_DIR="$REPO_ROOT/scripts/engaging"
      echo "INFO: using SLURM_SUBMIT_DIR as REPO_ROOT=$REPO_ROOT (stage=$stage)" >&2
      return 0
    fi
    echo "ERROR: SLURM_SUBMIT_DIR is set but is not a valid repository root (stage=$stage)." >&2
    echo "ERROR: attempted SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR" >&2
  fi

  echo "ERROR: repository root could not be resolved (stage=$stage)." >&2
  echo "ERROR: Export a validated REPO_ROOT from the launcher before sbatch." >&2
  echo "ERROR: Slurm spool copies of batch scripts are not the repository." >&2
  echo "ERROR: REPO_ROOT=${REPO_ROOT:-<unset>} SLURM_SUBMIT_DIR=${SLURM_SUBMIT_DIR:-<unset>}" >&2
  return 1
}

cementitious_source_engaging_helper() {
  local name="$1"
  local stage="${2:-unknown}"
  : "${REPO_ROOT:?REPO_ROOT must be set before sourcing helpers}"
  local path="$REPO_ROOT/scripts/engaging/$name"
  if [[ ! -r "$path" ]]; then
    echo "ERROR: missing readable Engaging helper for stage=$stage: $path" >&2
    return 1
  fi
  # shellcheck disable=SC1090
  source "$path"
}

# Locate and source this file using REPO_ROOT / SLURM_SUBMIT_DIR only (no BASH_SOURCE).
# Intended for the top of #SBATCH scripts. Sets REPO_ROOT and cds into it.
cementitious_bootstrap_from_env() {
  local stage="${1:-job}"
  local cand=""
  local helper=""
  for cand in "${REPO_ROOT:-}" "${SLURM_SUBMIT_DIR:-}"; do
    [[ -n "$cand" ]] || continue
    helper="${cand%/}/scripts/engaging/_cementitious_repo_root.sh"
    if [[ -f "$helper" ]]; then
      # shellcheck disable=SC1090
      source "$helper"
      cementitious_resolve_repo_root "$stage" || return 1
      cd "$REPO_ROOT" || return 1
      mkdir -p logs
      return 0
    fi
  done
  echo "ERROR: could not locate scripts/engaging/_cementitious_repo_root.sh (stage=$stage)." >&2
  echo "ERROR: REPO_ROOT=${REPO_ROOT:-<unset>} SLURM_SUBMIT_DIR=${SLURM_SUBMIT_DIR:-<unset>}" >&2
  return 1
}
