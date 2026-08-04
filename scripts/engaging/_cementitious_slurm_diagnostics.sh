#!/bin/bash
# Shared startup diagnostics for Cementitious Engaging stages (no secrets).
# shellcheck shell=bash

cementitious_log_diagnostics() {
  local stage="${1:-unknown}"
  local shard_path="${2:-}"
  echo "=== Cementitious Slurm diagnostics ($stage) ==="
  echo "hostname=$(hostname)"
  echo "SLURM_JOB_ID=${SLURM_JOB_ID:-}"
  echo "SLURM_ARRAY_JOB_ID=${SLURM_ARRAY_JOB_ID:-}"
  echo "SLURM_ARRAY_TASK_ID=${SLURM_ARRAY_TASK_ID:-}"
  echo "SLURM_CPUS_ON_NODE=${SLURM_CPUS_ON_NODE:-}"
  echo "SLURM_CPUS_PER_TASK=${SLURM_CPUS_PER_TASK:-}"
  echo "SLURM_MEM_PER_NODE=${SLURM_MEM_PER_NODE:-}"
  echo "SLURM_MEM_PER_CPU=${SLURM_MEM_PER_CPU:-}"
  echo "SLURM_JOB_PARTITION=${SLURM_JOB_PARTITION:-}"
  echo "CEMENTITIOUS_WORKERS=${CEMENTITIOUS_WORKERS:-1}"
  echo "CEMENTITIOUS_BATCH_SIZE=${CEMENTITIOUS_BATCH_SIZE:-}"
  echo "CEMENTITIOUS_MAX_IN_FLIGHT=${CEMENTITIOUS_MAX_IN_FLIGHT:-}"
  echo "CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB=${CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB:-}"
  echo "CEMENTITIOUS_MAX_RECORDS=${CEMENTITIOUS_MAX_RECORDS:-}"
  echo "OUT=${OUT:-}"
  if [[ -n "$shard_path" && -f "$shard_path" ]]; then
    echo "shard_path=$shard_path"
    echo "shard_bytes=$(wc -c < "$shard_path" | tr -d ' ')"
  elif [[ -n "$shard_path" ]]; then
    echo "shard_path=$shard_path (missing)"
  fi
  echo "OPENAI_API_KEY: $([ -n "${OPENAI_API_KEY:-}" ] && echo set || echo unset)"
  echo "TAVILY_API_KEY: $([ -n "${TAVILY_API_KEY:-}" ] && echo set || echo unset)"
  echo "=============================================="
}
