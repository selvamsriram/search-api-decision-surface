#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
export PYTHONPATH=src:.

COMMON_ARGS=(
  --execute
  --resume
  --concurrency 1
  --max-document-chars 20000
  --max-tokens 16384
  --parse-retries 1
  --execution-retries 2
  --throttle-sleep-seconds 60
  --progress-every 25
  --reuse-query-url-duplicates
)

echo "[$(date)] Starting Brave Kimi v3 all-visible with temporary cache"
python3 scripts/run_llm_judge.py \
  --trace data/traces/phase1_v1_brave_gpt54_fetch_tool_jina_100.jsonl \
  --cache-jsonl results/llm_judge/kimi_document_judge_surface_v3_brave_100_top3search.jsonl \
  --output results/llm_judge/kimi_document_judge_surface_v3_brave_100_all_visible.jsonl \
  "${COMMON_ARGS[@]}"

echo "[$(date)] Starting Tavily Kimi v3 all-visible"
python3 scripts/run_llm_judge.py \
  --trace data/traces/phase1_v1_tavily_gpt54_fetch_tool_jina_100.jsonl \
  --output results/llm_judge/kimi_document_judge_surface_v3_tavily_100_all_visible.jsonl \
  "${COMMON_ARGS[@]}"

echo "[$(date)] Starting Firecrawl Kimi v3 all-visible"
python3 scripts/run_llm_judge.py \
  --trace data/traces/phase1_v1_firecrawl_gpt54_fetch_tool_jina_100.jsonl \
  --output results/llm_judge/kimi_document_judge_surface_v3_firecrawl_100_all_visible.jsonl \
  "${COMMON_ARGS[@]}"

echo "[$(date)] Finished all Kimi v3 all-visible runs"
