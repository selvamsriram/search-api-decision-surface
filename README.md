# searchapi-hard-eval

V1 infrastructure for studying how commercial search APIs affect hard search-augmented QA performance on SealQA Hard.

The current V1 path runs a frozen tool-calling agent over the 100-query Phase 1 sample using:

- Search provider: Brave Search API by default; Exa, Tavily, and Firecrawl remain available as options
- Page evidence: provider-neutral local fetch/extract layer for returned result URLs
- Model provider: GPT-5.4 deployment on Azure OpenAI
- Output artifact: versioned JSONL traces with every model turn, search call, retrieved document, token count, latency, and final answer

## Repository Layout

```text
config/
  experiment.yaml                  # V1 run defaults
  models/azure_gpt54.yaml          # Azure model env names and defaults
  providers/brave.yaml             # Brave provider defaults
  providers/exa.yaml               # Exa provider defaults, optional
  providers/tavily.yaml            # Tavily provider defaults, optional
  providers/firecrawl.yaml         # Firecrawl provider defaults, optional
data/
  raw/seal-hard.jsonl              # Local pinned SealQA Hard source rows
  queries/phase1_100.json          # Deterministic 100-query Phase 1 sample
  page_cache/                      # Local extracted-page artifacts, created at runtime
  100-dataset-selection-rationale.md
  trace-schema-v1.md
scripts/
  select_phase1_queries.py         # Rebuild the 100-query sample
  run_phase1.py                    # Run Brave/Exa/Tavily/Firecrawl + Azure GPT-5.4 agent
  evaluate_traces.py               # Compute V1 offline metrics from trace JSONL
  build_provider_comparison.py     # Build provider-comparison metrics across trace files
  run_llm_judge.py                 # Prepare or run Kimi K2.6 judge prompts over traces
  render_trace.py                  # Render one JSONL trace into a human-readable HTML view
  trace_dashboard.py               # Live browser dashboard for browsing trace JSONL files
src/searchapi_eval/
  agent/                           # Prompt templates, tool schema, agent loop, trace helpers
  data/                            # SealQA loader and sampler
  evaluation/                      # EM/F1 and trace-derived metrics
  models/                          # Azure OpenAI client
  page_fetcher/                    # Provider-neutral URL fetch and page extraction
  providers/                       # Brave, Exa, Tavily, and Firecrawl providers
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

# Provider-neutral page fetch/extract layer
PAGE_FETCH_ENABLED=true
PAGE_FETCH_CACHE_DIR=data/page_cache
PAGE_FETCH_TIMEOUT_SECONDS=15
PAGE_FETCH_MAX_BYTES=2000000
PAGE_FETCH_CONCURRENCY=4
PAGE_FETCH_BACKEND=local
JINA_READER_BASE_URL=https://r.jina.ai
JINA_API_KEY=your_jina_api_key_here
FETCH_PAGE_TOOL_ENABLED=false

# Exa, still available with SEARCH_PROVIDER=exa or --provider exa
EXA_API_KEY=your_exa_api_key_here

# Tavily, available with SEARCH_PROVIDER=tavily or --provider tavily
TAVILY_API_KEY=tvly_your_tavily_api_key_here
TAVILY_SEARCH_DEPTH=basic
TAVILY_TOPIC=general
TAVILY_INCLUDE_RAW_CONTENT=false
TAVILY_INCLUDE_FAVICON=false

# Firecrawl, available with SEARCH_PROVIDER=firecrawl or --provider firecrawl
FIRECRAWL_API_KEY=fc_your_firecrawl_api_key_here
FIRECRAWL_COUNTRY=US
FIRECRAWL_LOCATION=
FIRECRAWL_INCLUDE_MARKDOWN=false
FIRECRAWL_IGNORE_INVALID_URLS=false
FIRECRAWL_TIMEOUT_MS=60000

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com
AZURE_OPENAI_API_KEY=your_azure_openai_api_key_here
AZURE_OPENAI_DEPLOYMENT=gpt-5.4
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_MAX_TOKENS_FIELD=max_tokens

# Optional model pricing for cost accounting
AZURE_INPUT_PRICE_PER_1K_USD=0
AZURE_OUTPUT_PRICE_PER_1K_USD=0

# Optional LLM judge: Kimi K2.6 on Azure
KIMI_AZURE_OPENAI_ENDPOINT=https://your-kimi-resource-name.openai.azure.com
KIMI_AZURE_OPENAI_API_KEY=your_kimi_azure_openai_api_key_here
KIMI_AZURE_OPENAI_DEPLOYMENT=kimi-k2.6
KIMI_AZURE_OPENAI_API_VERSION=2024-10-21
KIMI_AZURE_OPENAI_MAX_TOKENS_FIELD=max_tokens
KIMI_AZURE_MODEL_ID=azure:kimi-k2.6
KIMI_AZURE_TEMPERATURE=0
KIMI_AZURE_MAX_TOKENS=4096
KIMI_AZURE_INPUT_PRICE_PER_1K_USD=0
KIMI_AZURE_OUTPUT_PRICE_PER_1K_USD=0
```

You can also set the same values as shell environment variables. Shell variables take precedence over `.env`.

### Required Values

- `BRAVE_SEARCH_API_KEY`: Brave Search API subscription token. The provider sends it as the `X-Subscription-Token` header. The code also accepts `BRAVE_API_KEY` or `BRAVE_SEARCH_SUBSCRIPTION_TOKEN` as aliases, but `BRAVE_SEARCH_API_KEY` is the preferred name.
- `AZURE_OPENAI_ENDPOINT`: Azure resource endpoint, for example `https://my-resource.openai.azure.com`. If you paste a longer Azure URL such as `/openai/responses?...`, the runner normalizes it back to the resource root.
- `AZURE_OPENAI_API_KEY`: Azure OpenAI API key.
- `AZURE_OPENAI_DEPLOYMENT`: the Azure deployment name for GPT-5.4. This is often not the same as the model name.
- `AZURE_OPENAI_API_VERSION`: defaults in examples to `2024-10-21`.

### Optional Values

- `SEARCH_PROVIDER`: `brave` by default. Set to `exa`, `tavily`, or `firecrawl` to use those providers instead.
- `SEARCH_COST_PER_QUERY_USD`: generic search cost estimate used in traces.
- `BRAVE_SEARCH_COUNTRY`: defaults to `US`.
- `BRAVE_SEARCH_LANG`: defaults to `en`.
- `BRAVE_SEARCH_UI_LANG`: defaults to `en-US`.
- `BRAVE_SEARCH_SAFESEARCH`: defaults to `moderate`.
- `EXA_API_KEY`: required only when running with `SEARCH_PROVIDER=exa` or `--provider exa`.
- `TAVILY_API_KEY`: required only when running with `SEARCH_PROVIDER=tavily` or `--provider tavily`. Sent as `Authorization: Bearer <key>`.
- `TAVILY_SEARCH_DEPTH`: defaults to `basic`. Tavily supports `basic`, `advanced`, `fast`, and `ultra-fast`.
- `TAVILY_TOPIC`: defaults to `general`. Tavily also documents `news` and `finance`.
- `TAVILY_INCLUDE_RAW_CONTENT`: defaults to `false`. Leave this off for now because the repo already has a provider-neutral page fetch layer; turn it on only if you want Tavily's cleaned page extract in provider metadata too.
- `TAVILY_INCLUDE_FAVICON`: defaults to `false`.
- `FIRECRAWL_API_KEY`: required only when running with `SEARCH_PROVIDER=firecrawl` or `--provider firecrawl`. Sent as `Authorization: Bearer <key>`.
- `FIRECRAWL_COUNTRY`: defaults to `US`.
- `FIRECRAWL_LOCATION`: optional geo-targeting location string. Leave blank unless running a location-specific experiment.
- `FIRECRAWL_INCLUDE_MARKDOWN`: defaults to `false`. Firecrawl can scrape search results and return markdown in the search response, but this is off by default so the provider remains comparable with the repo's provider-neutral page fetch layer.
- `FIRECRAWL_IGNORE_INVALID_URLS`: defaults to `false`.
- `FIRECRAWL_TIMEOUT_MS`: Firecrawl-side request timeout in milliseconds, default `60000`.
- `PAGE_FETCH_ENABLED`: defaults to `true`. When enabled, the runner fetches and extracts every returned result URL before sending search documents back to the model. When `FETCH_PAGE_TOOL_ENABLED=true` or `--fetch-tool` is used, this automatic inclusion is disabled and search results remain snippet-only.
- `PAGE_FETCH_CACHE_DIR`: defaults to `data/page_cache`. Each fetched URL gets a gzip JSON artifact with the extracted text and fetch metadata.
- `PAGE_FETCH_TIMEOUT_SECONDS`: per-page HTTP timeout.
- `PAGE_FETCH_MAX_BYTES`: maximum response bytes read per URL before extraction. This is a download guard, not chunk selection.
- `PAGE_FETCH_CONCURRENCY`: number of page fetches to run in parallel per search result set.
- `PAGE_FETCH_BACKEND`: defaults to `local`. Set to `jina` to fetch page markdown through Jina Reader (`https://r.jina.ai/<url>`) instead of the local extractor.
- `JINA_READER_BASE_URL`: defaults to `https://r.jina.ai`.
- `JINA_API_KEY`: optional Jina AI key for higher Reader API rate limits. Sent as `Authorization: Bearer <key>` and never written to traces.
- `FETCH_PAGE_TOOL_ENABLED`: defaults to `false`. When enabled, exposes `fetch_page(document_id)` as a model tool so the agent chooses which search-result pages to open without copying long URLs.
- `AZURE_OPENAI_MAX_TOKENS_FIELD`: use `max_tokens` by default. If Azure says the deployment requires `max_completion_tokens`, the runner retries once with that field automatically.
- `AZURE_INPUT_PRICE_PER_1K_USD`, `AZURE_OUTPUT_PRICE_PER_1K_USD`: used only for trace cost estimates. These must be USD prices per 1K tokens, not token limits or TPM quotas. Leave them as `0` until pricing is confirmed.
- `KIMI_AZURE_OPENAI_ENDPOINT`, `KIMI_AZURE_OPENAI_API_KEY`, `KIMI_AZURE_OPENAI_DEPLOYMENT`: required only when running LLM judge execution with `scripts/run_llm_judge.py --execute`.
- `KIMI_AZURE_OPENAI_API_VERSION`, `KIMI_AZURE_OPENAI_MAX_TOKENS_FIELD`, `KIMI_AZURE_MAX_TOKENS`: Kimi judge request settings. The default judge cap is `4096` output tokens because Kimi may spend tokens in hidden reasoning before emitting JSON.
- `KIMI_AZURE_INPUT_PRICE_PER_1K_USD`, `KIMI_AZURE_OUTPUT_PRICE_PER_1K_USD`: optional judge-cost accounting.

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

### Tavily Search API

Tavily is available as another provider option:

```bash
SEARCH_PROVIDER=tavily PYTHONPATH=src python3 scripts/run_phase1.py --limit 1
```

or:

```bash
PYTHONPATH=src python3 scripts/run_phase1.py --provider tavily --limit 1
```

Docs used for this integration:

- [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)

The implementation uses Tavily's POST search endpoint:

```text
POST https://api.tavily.com/search
Authorization: Bearer <TAVILY_API_KEY>
Content-Type: application/json
```

Request body fields used by default:

- `query`: model-generated search query
- `search_depth`: `TAVILY_SEARCH_DEPTH`, default `basic`
- `topic`: `TAVILY_TOPIC`, default `general`
- `max_results`: `--max-results`, capped at Tavily's documented maximum of `20`
- `include_answer`: `false`
- `include_images`: `false`
- `include_image_descriptions`: `false`
- `include_favicon`: `TAVILY_INCLUDE_FAVICON`, default `false`
- `include_raw_content`: `TAVILY_INCLUDE_RAW_CONTENT`, default `false`

Tavily responses are normalized from `results[]` into the same trace result schema used by the other providers: `rank`, `title`, `url`, `snippet`, `domain`, and `provider_metadata`.

### Firecrawl Search API

Firecrawl is available as another provider option:

```bash
SEARCH_PROVIDER=firecrawl PYTHONPATH=src python3 scripts/run_phase1.py --limit 1
```

or:

```bash
PYTHONPATH=src python3 scripts/run_phase1.py --provider firecrawl --limit 1
```

Docs used for this integration:

- [Firecrawl Search API](https://docs.firecrawl.dev/api-reference/endpoint/search)

The implementation uses Firecrawl's V2 POST search endpoint:

```text
POST https://api.firecrawl.dev/v2/search
Authorization: Bearer <FIRECRAWL_API_KEY>
Content-Type: application/json
```

Request body fields used by default:

- `query`: model-generated search query
- `limit`: `--max-results`, capped at Firecrawl's documented maximum of `100`
- `sources`: `["web"]`
- `country`: `FIRECRAWL_COUNTRY`, default `US`
- `location`: `FIRECRAWL_LOCATION`, omitted when blank
- `timeout`: `FIRECRAWL_TIMEOUT_MS`, default `60000`
- `ignoreInvalidURLs`: `FIRECRAWL_IGNORE_INVALID_URLS`, default `false`
- `scrapeOptions`: omitted by default; enabled only when `FIRECRAWL_INCLUDE_MARKDOWN=true`

Firecrawl can return scraped markdown directly from search results. For the main provider-comparison runs, keep `FIRECRAWL_INCLUDE_MARKDOWN=false` so Firecrawl is evaluated as a search provider and the same local page-fetch layer is used across Brave, Tavily, and Firecrawl.

Firecrawl responses are normalized from `data.web[]` into the same trace result schema used by the other providers: `rank`, `title`, `url`, `snippet`, `domain`, and `provider_metadata`.

## Page Fetching And Extraction

Search providers only supply snippets and metadata. V1.5 adds a provider-neutral page fetcher that runs after Brave/Exa/Tavily/Firecrawl returns results and before the model sees the tool response.

Flow:

```text
search_web(query)
  -> Brave/Exa/Tavily/Firecrawl returns ranked URLs
  -> page_fetcher fetches each URL with the selected backend
  -> local extractor or Jina Reader converts the page to text/markdown
  -> full extracted text is rendered inside <extracted_page>
  -> trace links each result to a page artifact
```

The fetcher is intentionally separate from provider code, so the same evidence layer works for Brave, Exa, Tavily, Firecrawl, or any future search API. With `PAGE_FETCH_BACKEND=local`, it tries `trafilatura` for HTML extraction when available and falls back to a stdlib HTML text extractor. With `PAGE_FETCH_BACKEND=jina`, it calls Jina Reader and stores the returned markdown as the extracted page text.

Disable page fetching for snippet-only runs:

```bash
PYTHONPATH=src python3 scripts/run_phase1.py --no-page-fetch --limit 1
```

Run the agentic-fetch architecture, where `search_web` returns snippets/URLs and the model chooses when to call `fetch_page`:

```bash
PYTHONPATH=src python3 scripts/run_phase1.py \
  --fetch-tool \
  --limit 1
```

Use Jina Reader markdown for page fetches:

```bash
PYTHONPATH=src python3 scripts/run_phase1.py \
  --fetch-tool \
  --page-fetch-backend jina \
  --limit 1
```

Each fetched page artifact is stored as gzip JSON under `data/page_cache` and includes:

- original URL, normalized URL, final URL after redirects
- fetch backend and, for Jina Reader, the reader URL
- HTTP status, content type, byte truncation flag, and fetch latency
- extractor method, extracted text, text hash, character count, and token estimate
- search context: provider, search query, rank, title, snippet, and domain

## Prompt Templates

All prompt text is stored as Liquid-style templates under [src/searchapi_eval/agent/prompts](src/searchapi_eval/agent/prompts):

- [system_search_only.liquid](src/searchapi_eval/agent/prompts/system_search_only.liquid): frozen search-only system instructions for the original harness.
- [system_fetch_tool.liquid](src/searchapi_eval/agent/prompts/system_fetch_tool.liquid): system instructions for the `fetch_page` tool condition.
- [system.liquid](src/searchapi_eval/agent/prompts/system.liquid): compatibility copy of the frozen search-only system instructions.
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
    <document id="s1r1" rank="1">
      <document_id>s1r1</document_id>
      <title>...</title>
      <url>...</url>
      <domain>...</domain>
      <snippet>...</snippet>
      <extra_snippet>...</extra_snippet>
      <extracted_page>
        <fetch_status>success</fetch_status>
        <extractor>trafilatura</extractor>
        <artifact_path>data/page_cache/...json.gz</artifact_path>
        <content>
          Full extracted page text...
        </content>
      </extracted_page>
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
- `--provider`: `brave`, `exa`, `tavily`, or `firecrawl`; default is `brave`.
- `--page-fetch` / `--no-page-fetch`: enable or disable URL fetch/extract.
- `--fetch-tool` / `--no-fetch-tool`: expose `fetch_page` as a model tool. Search results are snippet-only in this mode; selected pages are recorded in `fetches[]`.
- `--page-fetch-cache-dir`: where extracted page artifacts are written.
- `--page-fetch-backend`: `local` or `jina`.
- `--page-fetch-timeout`, `--page-fetch-max-bytes`, `--page-fetch-concurrency`: fetch controls.

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
- every page fetch summary, artifact path, extracted text, extractor method, HTTP status, and text size
- every rendered tool response in `iterations[].llm_request.messages`, including the full extracted page text that was sent to the model
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

## Provider Comparison Metrics

Build deterministic paper-facing metrics from existing trace files without making search or model calls:

```bash
PYTHONPATH=src python3 scripts/build_provider_comparison.py \
  --trace data/traces/phase1_v1_brave_gpt54_top3_pagefetch_phase1_100.jsonl \
  --trace data/traces/phase1_v1_tavily_gpt54_top3_pagefetch_phase1_100.jsonl \
  --trace data/traces/phase1_v1_firecrawl_gpt54_top3_pagefetch_phase1_100.jsonl \
  --output-dir results/provider_comparison/brave_tavily_firecrawl
```

Outputs:

- `provider_summary.json`: provider-level aggregates, pairwise matrices, and three-way outcome classes.
- `provider_per_query.jsonl`: one row per provider/query with deterministic retrieval, extraction, answer-string, tool-behavior, token, and failure metrics.
- `provider_domains.csv`: per-provider/domain fetch, extraction, and answer-string diagnostics.
- `provider_reliability.json`: historical failures, latest failures, and recovered transient failures.

The deterministic metrics intentionally distinguish source alignment from evidence availability:

- `gold_url_exact_hit`, `gold_url_prefix_hit`, `gold_domain_hit`, `gold_source_family_hit`
- `answer_in_snippet`, `answer_in_extra_snippets`, `answer_in_page`, `answer_in_any_retrieved_text`
- `gold_hit_but_no_answer_text`, `answer_text_without_gold_prefix`
- `wrong_with_answer_text_available`, `wrong_without_answer_text_available`

These are cheap diagnostics for choosing where the LLM judge should inspect first. They are not a replacement for support judging.

## Kimi Judge Prompts

The LLM judge pipeline is deliberately two-step. First prepare prompts for review without any model calls:

```bash
PYTHONPATH=src python3 scripts/run_llm_judge.py \
  --trace data/traces/phase1_v1_brave_gpt54_top3_pagefetch_phase1_100.jsonl \
  --trace data/traces/phase1_v1_tavily_gpt54_top3_pagefetch_phase1_100.jsonl \
  --trace data/traces/phase1_v1_firecrawl_gpt54_top3_pagefetch_phase1_100.jsonl \
  --query-id sealhard_0117c1361b85 \
  --output results/llm_judge/kimi_prompt_review_sample.jsonl
```

Review the prompt template before enabling execution:

- [document_support_judge.liquid](src/searchapi_eval/evaluation/prompts/document_support_judge.liquid)

The judge evaluates one retrieved document URL at a time. The prompt includes the question, gold answer, model final answer, and the single retrieved document rendered in the same XML shape used by the answer-generating model. That document view includes rank, title, URL, domain, snippet, provider extra snippets, page-fetch metadata, and extracted page content. By default, `--max-document-chars 0` includes the full extracted text visible to the answer model; set a positive value only when intentionally running a capped judge pass.

The current document-level judge schema is:

```json
{
  "contains_gold_answer": true,
  "supports_model_answer": false,
  "contradicts_gold_answer": false,
  "is_garbage": false,
  "garbage_reason": "",
  "answer_span": "short verbatim supporting span",
  "confidence": 0.92
}
```

`contains_gold_answer` means the document contains enough evidence to answer the question with the gold answer, not merely that the answer string appears.

Garbage detection has two layers:

- `document_garbage_precheck`: deterministic fetch-level garbage detection from tracked metadata, such as failed fetches, unsupported PDFs/Office/binary files, and empty extractions. This is never sent to Kimi.
- `judgment.is_garbage`: Kimi's content-level judgment from the prompt-visible document XML.
- `effective_is_garbage`: `true` when either layer marks the document as garbage.

After review and after adding the Kimi Azure keys to `.env`, run with `--execute`:

```bash
PYTHONPATH=src python3 scripts/run_llm_judge.py \
  --trace data/traces/phase1_v1_brave_gpt54_top3_pagefetch_phase1_100.jsonl \
  --trace data/traces/phase1_v1_tavily_gpt54_top3_pagefetch_phase1_100.jsonl \
  --trace data/traces/phase1_v1_firecrawl_gpt54_top3_pagefetch_phase1_100.jsonl \
  --output results/llm_judge/kimi_k26_judgments.jsonl \
  --execute
```

Without `--execute`, `scripts/run_llm_judge.py` only writes prompt records and makes no LLM calls.

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
results/llm_judge
results/provider_comparison/brave_tavily_firecrawl
```

and extracted page artifacts from:

```text
data/page_cache
```

It lets you:

- pick a trace file from the sidebar
- pick an LLM judge file from the separate sidebar section
- search rows by query ID, trace ID, question, final answer, provider, or gold answer
- page through large JSONL files without loading the whole file into the browser
- select one row at a time for full inspection
- inspect run summary, final answer, gold answer, metrics, timeline, full LLM request snapshots, model responses, tool calls, and search results
- inspect judge-run aggregates, per-query judge aggregates, search-query groups, document-level judgments, garbage prechecks, Kimi prompts, and Kimi responses
- inspect deterministic offline metrics from provider-comparison artifacts, including exact match, F1, gold URL/domain/source-family alignment, answer-string availability, search reformulation, extraction status, large-page counts, token usage, reliability, pairwise matrices, and same-query provider comparisons
- expand full raw provider responses for each search call
- inspect page fetch status for each search result and click through to the full extracted page artifact

Override the judge directory when needed:

```bash
PYTHONPATH=src python3 scripts/trace_dashboard.py \
  --judge-dir results/llm_judge
```

Override the provider-comparison artifact directory when needed:

```bash
PYTHONPATH=src python3 scripts/trace_dashboard.py \
  --provider-comparison-dir results/provider_comparison/brave_tavily_firecrawl
```

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

The renderer streams the JSONL line by line when selecting a trace, so it is safe to use with large run files. The HTML report includes run metadata, final answer, gold answer, metrics, a timeline, full LLM request snapshots, model responses, tool calls, normalized search results, and extracted page content.

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

- Runtime calls use the Python standard library plus optional `trafilatura` HTML extraction when installed.
- The prompt renderer supports the Liquid subset currently used by the templates: `{{ variable }}`, dotted paths, `{% for item in items %}`, and `{% include "path.liquid" %}`.
- `.env` is intentionally gitignored. Do not commit real keys.
