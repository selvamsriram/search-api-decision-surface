#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
export PYTHONPATH=src:.

echo "[$(date)] Starting Firecrawl Kimi v3 all-visible on Kimi env slot 2"
python3 scripts/run_llm_judge.py \
  --trace data/traces/phase1_v1_firecrawl_gpt54_fetch_tool_jina_100.jsonl \
  --output results/llm_judge/kimi_document_judge_surface_v3_firecrawl_100_all_visible.jsonl \
  --execute \
  --resume \
  --reuse-query-url-duplicates \
  --kimi-env-slot 2 \
  --concurrency 1 \
  --max-document-chars 20000 \
  --max-tokens 16384 \
  --parse-retries 1 \
  --execution-retries 2 \
  --throttle-sleep-seconds 60 \
  --progress-every 25

echo "[$(date)] Finished Firecrawl Kimi v3 all-visible on Kimi env slot 2"
