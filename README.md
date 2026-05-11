# searchapi-hard-eval

V1 infrastructure for studying how commercial search APIs affect hard search-augmented QA performance on SealQA Hard.

The current V1 path runs a frozen tool-calling agent over the 100-query Phase 1 sample using:

- Search provider: Brave Search API by default; Exa remains available as an option
- Model provider: GPT-5.4 deployment on Azure OpenAI
- Output artifact: versioned JSONL traces with every model turn, search call, retrieved document, token count, latency, and final answer

## Repository Layout

```text
config/
  experiment.yaml                  # V1 run defaults
  models/azure_gpt54.yaml          # Azure model env names and defaults
  providers/brave.yaml             # Brave provider defaults
  providers/exa.yaml               # Exa provider defaults, optional
data/
  raw/seal-hard.jsonl              # Local pinned SealQA Hard source rows
  queries/phase1_100.json          # Deterministic 100-query Phase 1 sample
  100-dataset-selection-rationale.md
  trace-schema-v1.md
scripts/
  select_phase1_queries.py         # Rebuild the 100-query sample
  run_phase1.py                    # Run Brave/Exa + Azure GPT-5.4 agent
  evaluate_traces.py               # Compute V1 offline metrics from trace JSONL
  render_trace.py                  # Render one JSONL trace into a human-readable HTML view
  trace_dashboard.py               # Live browser dashboard for browsing trace JSONL files
src/searchapi_eval/
  agent/                           # Prompt templates, tool schema, agent loop, trace helpers
  data/                            # SealQA loader and sampler
  evaluation/                      # EM/F1 and trace-derived metrics
  models/                          # Azure OpenAI client
  providers/                       # Brave and Exa providers
tests/
```

## Keys And Secrets

The runner auto-loads a repo-root `.env` file before creating the search and Azure clients. The `.env` file is ignored by git.

Use [.env.example](.env.example) as the template and put the real keys in `.env`:

```bash
# Default search provider for V1
SEARCH_PROVIDER=brave
SEARCH_COST_PER_QUERY_USD=0

# Brave Search API
BRAVE_SEARCH_API_KEY=your_brave_search_api_key_here
BRAVE_SEARCH_COUNTRY=US
BRAVE_SEARCH_LANG=en
BRAVE_SEARCH_UI_LANG=en-US
BRAVE_SEARCH_SAFESEARCH=moderate

# Exa, still available with SEARCH_PROVIDER=exa or --provider exa
EXA_API_KEY=your_exa_api_key_here

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com
AZURE_OPENAI_API_KEY=your_azure_openai_api_key_here
AZURE_OPENAI_DEPLOYMENT=gpt-5.4
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_MAX_TOKENS_FIELD=max_tokens

# Optional model pricing for cost accounting
AZURE_INPUT_PRICE_PER_1K_USD=0
AZURE_OUTPUT_PRICE_PER_1K_USD=0
```

You can also set the same values as shell environment variables. Shell variables take precedence over `.env`.

### Required Values

- `BRAVE_SEARCH_API_KEY`: Brave Search API subscription token. The provider sends it as the `X-Subscription-Token` header. The code also accepts `BRAVE_API_KEY` or `BRAVE_SEARCH_SUBSCRIPTION_TOKEN` as aliases, but `BRAVE_SEARCH_API_KEY` is the preferred name.
- `AZURE_OPENAI_ENDPOINT`: Azure resource endpoint, for example `https://my-resource.openai.azure.com`. If you paste a longer Azure URL such as `/openai/responses?...`, the runner normalizes it back to the resource root.
- `AZURE_OPENAI_API_KEY`: Azure OpenAI API key.
- `AZURE_OPENAI_DEPLOYMENT`: the Azure deployment name for GPT-5.4. This is often not the same as the model name.
- `AZURE_OPENAI_API_VERSION`: defaults in examples to `2024-10-21`.

### Optional Values

- `SEARCH_PROVIDER`: `brave` by default. Set to `exa` to use Exa instead.
- `SEARCH_COST_PER_QUERY_USD`: generic search cost estimate used in traces.
- `BRAVE_SEARCH_COUNTRY`: defaults to `US`.
- `BRAVE_SEARCH_LANG`: defaults to `en`.
- `BRAVE_SEARCH_UI_LANG`: defaults to `en-US`.
- `BRAVE_SEARCH_SAFESEARCH`: defaults to `moderate`.
- `EXA_API_KEY`: required only when running with `SEARCH_PROVIDER=exa` or `--provider exa`.
- `AZURE_OPENAI_MAX_TOKENS_FIELD`: use `max_tokens` by default. If Azure says the deployment requires `max_completion_tokens`, the runner retries once with that field automatically.
- `AZURE_INPUT_PRICE_PER_1K_USD`, `AZURE_OUTPUT_PRICE_PER_1K_USD`: used only for trace cost estimates. These must be USD prices per 1K tokens, not token limits or TPM quotas. Leave them as `0` until pricing is confirmed.

## Search Providers

### Brave Search API

Brave is the default provider for V1.

Docs used for this integration:

- [Brave Web Search GET](https://api-dashboard.search.brave.com/api-reference/web/search/get)
- [Brave Web Search POST](https://api-dashboard.search.brave.com/api-reference/web/search/post)

The implementation uses the GET endpoint:

```text
GET https://api.search.brave.com/res/v1/web/search
X-Subscription-Token: <BRAVE_SEARCH_API_KEY>
Accept: application/json
Accept-Encoding: gzip
```

Query parameters used by default:

- `q`: model-generated search query
- `count`: `--max-results`, capped at Brave's maximum of `20`
- `offset`: `0`
- `country`: `BRAVE_SEARCH_COUNTRY`, default `US`
- `search_lang`: `BRAVE_SEARCH_LANG`, default `en`
- `ui_lang`: `BRAVE_SEARCH_UI_LANG`, default `en-US`
- `safesearch`: `BRAVE_SEARCH_SAFESEARCH`, default `moderate`
- `spellcheck`: `true`
- `text_decorations`: `false`
- `result_filter`: `web`

Brave responses are normalized from `web.results[]` into the same trace result schema used for Exa: `rank`, `title`, `url`, `snippet`, `domain`, and `provider_metadata`.

### Exa Search API

Exa remains available for comparison or later experiments:

```bash
SEARCH_PROVIDER=exa PYTHONPATH=src python3 scripts/run_phase1.py --limit 1
```

or:

```bash
PYTHONPATH=src python3 scripts/run_phase1.py --provider exa --limit 1
```

## Prompt Templates

All prompt text is stored as Liquid-style templates under [src/searchapi_eval/agent/prompts](src/searchapi_eval/agent/prompts):

- [system.liquid](src/searchapi_eval/agent/prompts/system.liquid): frozen system instructions.
- [user_query.liquid](src/searchapi_eval/agent/prompts/user_query.liquid): wraps each SealQA question in `<user_query>`.
- [search_documents.liquid](src/searchapi_eval/agent/prompts/search_documents.liquid): wraps every search result set in `<search_documents>`.
- [neutral_research_example.liquid](src/searchapi_eval/agent/prompts/examples/neutral_research_example.liquid): a realistic, neutral example showing how to separate system instructions, user query, retrieved documents, and decision criteria.

The model sees clear boundaries:

```xml
<system_instructions>
...
</system_instructions>

<user_query>
...
</user_query>

<search_documents>
  <search query="..." provider="brave">
    <document rank="1">
      <title>...</title>
      <url>...</url>
      <domain>...</domain>
      <snippet>...</snippet>
      <extra_snippet>...</extra_snippet>
    </document>
  </search>
</search_documents>
```

The example is intentionally framed as decision guidance, not a preferred behavior. It says that answering, searching again, and abstaining are all valid depending on evidence and remaining budget.

## Dataset Selection

The V1 sample is 100 SealQA Hard queries selected by deterministic proportional stratified sampling.

Primary strata:

- `freshness`
- `search_results`
- `topic`

Coverage checks:

- `question_types`
- `effective_year`

Generated artifacts:

- [data/queries/phase1_100.json](data/queries/phase1_100.json)
- [data/100-dataset-selection-rationale.md](data/100-dataset-selection-rationale.md)

Rebuild the selection:

```bash
PYTHONPATH=src python3 scripts/select_phase1_queries.py
```

## Running A Pilot

Run one selected query:

```bash
PYTHONPATH=src python3 scripts/run_phase1.py --limit 1
```

That command uses Brave by default and writes to `data/traces/phase1_v1_brave_gpt54.jsonl`.

Run two selected queries:

```bash
PYTHONPATH=src python3 scripts/run_phase1.py \
  --limit 2 \
  --output data/traces/phase1_v1_brave_gpt54.jsonl
```

Run a specific query ID:

```bash
PYTHONPATH=src python3 scripts/run_phase1.py \
  --query-id sealhard_0117c1361b85
```

Resume a run without duplicating query IDs already present in the output JSONL:

```bash
PYTHONPATH=src python3 scripts/run_phase1.py --resume
```

Useful run options:

- `--limit`: number of selected queries to run.
- `--offset`: start position in the selected query list.
- `--max-iterations`: default `10`.
- `--max-results`: default `10`.
- `--output`: destination JSONL trace file.
- `--run-id`: label stored on every trace row.
- `--provider`: `brave` or `exa`; default is `brave`.

## Trace Output

Each query execution appends one JSON object to the output JSONL. The schema version is `searchapi_trace_v1`.

Trace docs:

- [data/trace-schema-v1.md](data/trace-schema-v1.md)

Each trace includes:

- query metadata, gold answer, and gold URLs for offline evaluation
- provider and model IDs
- every LLM request snapshot, including rendered messages, tool schema, temperature, deployment, API version, max token setting, and tool choice
- every LLM response, tool call, token usage, latency, and loop decision
- every search query
- every normalized result with title, URL, domain, snippet, rank, and provider metadata
- raw provider response for auditability
- model token usage and latency per iteration
- search latency per retrieval
- final response, extracted answer, `answered`, `ceiling_hit`
- total searches, total tokens, wall time, and estimated cost
- provider/model failures in `errors[]`; failed pilot runs are still written to JSONL for auditability

Gold answers and gold URLs are stored for grading and metrics. They are not passed to the model during the agent run.

## Offline Metrics

Compute V1 per-query metrics:

```bash
PYTHONPATH=src python3 scripts/evaluate_traces.py \
  --input data/traces/phase1_v1_brave_gpt54.jsonl \
  --output results/per_query_metrics.json
```

Currently implemented:

- exact match
- token F1
- total search calls
- reformulation rate
- redundant search rate
- source diversity
- gold document hit
- ceiling hit
- premature termination
- coarse failure mode
- token totals
- estimated total cost

## HTML Trace Viewer

JSONL remains the canonical artifact, but reviewing raw traces gets painful quickly.

For day-to-day scrutiny, use the live dashboard:

```bash
PYTHONPATH=src python3 scripts/trace_dashboard.py
```

Open:

```text
http://127.0.0.1:8765
```

The dashboard automatically loads JSONL files from:

```text
data/traces
```

It lets you:

- pick a trace file from the sidebar
- search rows by query ID, trace ID, question, final answer, provider, or gold answer
- page through large JSONL files without loading the whole file into the browser
- select one row at a time for full inspection
- inspect run summary, final answer, gold answer, metrics, timeline, full LLM request snapshots, model responses, tool calls, and search results
- expand full raw provider responses for each search call

For one-off static reports, render a single trace into an HTML file:

```bash
PYTHONPATH=src python3 scripts/render_trace.py \
  --input data/traces/phase1_v1_brave_gpt54_smoke_latest.jsonl \
  --latest
```

By default, the viewer writes to:

```text
results/trace_views/<trace_id>.html
```

Useful selectors for large JSONL files:

```bash
# Latest row in the file
PYTHONPATH=src python3 scripts/render_trace.py --input data/traces/phase1_v1_brave_gpt54.jsonl --latest

# Specific trace
PYTHONPATH=src python3 scripts/render_trace.py --input data/traces/phase1_v1_brave_gpt54.jsonl --trace-id trace_...

# Latest run for a query id
PYTHONPATH=src python3 scripts/render_trace.py --input data/traces/phase1_v1_brave_gpt54.jsonl --query-id sealhard_0117c1361b85 --latest
```

The renderer streams the JSONL line by line when selecting a trace, so it is safe to use with large run files. The HTML report includes run metadata, final answer, gold answer, metrics, a timeline, full LLM request snapshots, model responses, tool calls, and normalized search results.

Planned next metrics from the proposal:

- STFU with LLM judge over retrieved documents
- Useful Doc Rank
- Retrieval Precision@10
- dual-order LLM-as-judge correctness
- hallucination rate
- bootstrap confidence intervals
- cross-dimensional aggregates
- Pareto frontier

## Development Checks

```bash
PYTHONPATH=src python3 -m compileall src scripts tests
PYTHONPATH=src python3 -m pytest -q
```

## Notes

- The V1 implementation uses only the Python standard library for runtime calls.
- The prompt renderer supports the Liquid subset currently used by the templates: `{{ variable }}`, dotted paths, `{% for item in items %}`, and `{% include "path.liquid" %}`.
- `.env` is intentionally gitignored. Do not commit real keys.
