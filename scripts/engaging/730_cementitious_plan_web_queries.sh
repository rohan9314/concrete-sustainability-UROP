#!/bin/bash
# MIT Engaging — deterministic web query planning (no Tavily/LLM). Safe on login node.
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$_SCRIPT_DIR/../.." && pwd)}"
cd "$REPO_ROOT"

: "${RESULTS_ROOT:?Set RESULTS_ROOT}"
# shellcheck source=scripts/engaging/_resolve_cementitious_out.sh
source "$_SCRIPT_DIR/_resolve_cementitious_out.sh"
resolve_cementitious_out || exit 1

echo "REPO_ROOT=$REPO_ROOT"
echo "RESULTS_ROOT=$RESULTS_ROOT"
echo "OUT=$OUT"
echo "SELECTED_SUBCATEGORIES=${SELECTED_SUBCATEGORIES:-<all>}"
echo "SELECTED_SUB_SUBCATEGORIES=${SELECTED_SUB_SUBCATEGORIES:-<all>}"
echo "WEB_QUERIES_PER_SUBCATEGORY=${WEB_QUERIES_PER_SUBCATEGORY:-3}"
echo "WEB_QUERIES_PER_SUB_SUBCATEGORY=${WEB_QUERIES_PER_SUB_SUBCATEGORY:-5}"
echo "WEB_RESULTS_PER_QUERY=${WEB_RESULTS_PER_QUERY:-10}"
echo "WEB_MAX_URLS_PER_BRANCH=${WEB_MAX_URLS_PER_BRANCH:-50}"
echo "WEB_MAX_TOTAL_URLS=${WEB_MAX_TOTAL_URLS:-1000}"
echo "WEB_SEARCH_SHARD_SIZE=${WEB_SEARCH_SHARD_SIZE:-10}"
echo "TAVILY_API_KEY: $([ -n "${TAVILY_API_KEY:-}" ] && echo set || echo unset)"

mkdir -p "$OUT"
python -m pipeline.cementitious.cluster plan-web-queries --output "$OUT"

echo "Web search array range: $(tr -d '\n' < "$OUT/metadata/web_search_array_range.txt" || true)"
echo "Plan complete -> $OUT/checkpoints/plan_web_queries.complete"
