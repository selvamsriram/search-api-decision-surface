# searchapi-hard-eval

Developer infrastructure for evaluating how commercial search APIs shape the
behavior of tool-using language agents.

The submitted paper is:

**Beyond Answer Accuracy: Search APIs as Decision Surfaces for Tool-Using Agents**

The code runs a frozen tool-calling QA agent on a deterministic 100-question
SealQA-Hard sample, varies only the search provider, records full traces, and
derives answer, retrieval, fetch, judge, and provider-comparison metrics.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
```

The test suite is offline and should not require API keys.

## Secrets

Copy `.env.example` to `.env` and fill in real credentials locally:

```bash
cp .env.example .env
```

The repo-root `.env` file is ignored by git. Shell environment variables take
precedence over values loaded from `.env`.

Common required variables for live runs:

- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_DEPLOYMENT`
- `BRAVE_SEARCH_API_KEY`, `TAVILY_API_KEY`, or `FIRECRAWL_API_KEY`
- `JINA_API_KEY`, optional but useful for the Jina Reader fetch backend
- `KIMI_AZURE_OPENAI_*`, required only for executed judge runs

## Layout

```text
config/                         Provider, model, and experiment defaults
data/raw/                       Pinned SealQA-Hard source rows
data/queries/                   Deterministic Phase 1 query sample
data/traces/                    Canonical paper traces plus archived runs
docs/archive/                   Historical planning and draft notes
paper/                          Submitted paper source, PDFs, and arXiv package
results/                        Canonical paper outputs plus archived outputs
scripts/                        Developer CLIs for runs, metrics, judges, views
src/searchapi_eval/             Reusable Python package
tests/                          Offline unit tests
```

## Canonical Paper Artifacts

The current paper build depends on these files:

```text
data/queries/phase1_100.json
data/traces/phase1_v1_brave_gpt54_fetch_tool_jina_100.jsonl
data/traces/phase1_v1_tavily_gpt54_fetch_tool_jina_100.jsonl
data/traces/phase1_v1_firecrawl_gpt54_fetch_tool_jina_100.jsonl
results/em_vs_semantic_audit.tsv
results/llm_judge/kimi_document_judge_surface_v3_brave_100_all_visible.jsonl
results/llm_judge/kimi_document_judge_surface_v3_tavily_100_all_visible.jsonl
results/llm_judge/kimi_document_judge_surface_v3_firecrawl_100_all_visible.jsonl
results/provider_comparison/brave_tavily_firecrawl_fetch_tool_jina/
```

Older smoke runs, prompt-review judge files, and previous provider-comparison
families are kept under `data/traces/archive/`, `results/archive/`,
`results/llm_judge/archive/`, and `results/provider_comparison/archive/`.

## Running Experiments

Run the default provider from config/environment:

```bash
python3 scripts/run_phase1.py --limit 1
```

Equivalent installed entry point:

```bash
searchapi-run-phase1 --limit 1
```

Run a specific provider:

```bash
python3 scripts/run_phase1.py --provider brave --limit 1
python3 scripts/run_phase1.py --provider tavily --limit 1
python3 scripts/run_phase1.py --provider firecrawl --limit 1
```

Run the paper-style fetch-tool condition:

```bash
python3 scripts/run_phase1.py \
  --provider brave \
  --fetch-tool \
  --page-fetch-backend jina \
  --output data/traces/phase1_v1_brave_gpt54_fetch_tool_jina_100.jsonl
```

Repeat for Tavily and Firecrawl with provider-specific outputs.

## Metrics And Judging

Build provider-comparison metrics:

```bash
python3 scripts/build_provider_comparison.py \
  --trace data/traces/phase1_v1_brave_gpt54_fetch_tool_jina_100.jsonl \
  --trace data/traces/phase1_v1_tavily_gpt54_fetch_tool_jina_100.jsonl \
  --trace data/traces/phase1_v1_firecrawl_gpt54_fetch_tool_jina_100.jsonl \
  --output-dir results/provider_comparison/brave_tavily_firecrawl_fetch_tool_jina
```

Prepare Kimi judge prompts without executing model calls:

```bash
python3 scripts/run_llm_judge.py \
  --trace data/traces/phase1_v1_brave_gpt54_fetch_tool_jina_100.jsonl \
  --trace data/traces/phase1_v1_tavily_gpt54_fetch_tool_jina_100.jsonl \
  --trace data/traces/phase1_v1_firecrawl_gpt54_fetch_tool_jina_100.jsonl \
  --output results/llm_judge/kimi_prompt_review_sample.jsonl \
  --limit 10
```

Add `--execute` only when Kimi Azure credentials are configured and a live judge
run is intended.

## Trace Views

Render a trace HTML view:

```bash
python3 scripts/render_trace.py \
  --input data/traces/phase1_v1_brave_gpt54_fetch_tool_jina_100.jsonl \
  --latest
```

Start the local trace dashboard:

```bash
python3 scripts/trace_dashboard.py
```

Tracked HTML examples live in `results/trace_views/`.

## Paper

Build the submitted preprint and review PDFs:

```bash
cd paper
make preprint
make submission
```

Build the tracked arXiv source archive:

```bash
cd paper
make arxiv
```

The arXiv package is:

```text
paper/build/search-api-decision-surface-arxiv.tar.gz
```

`paper/build/arxiv/` is temporary staging output and is ignored.

## Git LFS

Large trace and judge JSONL files are stored through Git LFS. Before rebuilding
paper figures or rerunning audits, pull LFS artifacts:

```bash
git lfs pull
```

## Development Checks

```bash
python3 -m pytest -q
cd paper && make arxiv
```

No lint/format tooling is configured yet by design.
