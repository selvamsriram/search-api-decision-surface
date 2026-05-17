# SearchAPI Trace Schema V1

Each completed query run is appended as one JSON object to a JSONL file, typically `data/traces/phase1_v1_brave_gpt54.jsonl`.

## Top-Level Fields

| Field | Type | Purpose |
| --- | --- | --- |
| `schema_version` | string | Fixed to `searchapi_trace_v1` for this implementation. |
| `trace_id` | string | Unique ID for this query execution. |
| `run_id` | string | User/config supplied run label for grouping rows. |
| `started_at`, `ended_at` | string | UTC ISO timestamps. |
| `dataset` | object | Dataset name, subset, and selection ID. |
| `query_id`, `source_index`, `question` | string/int | Query identity and prompt text. |
| `gold_answer`, `gold_urls` | string/list | Offline grading inputs; never sent to the model. |
| `metadata` | object | `freshness`, `topic`, `search_results`, `question_types`, and `effective_year`. |
| `provider_id`, `model_id` | string | Experimental cell identifiers. |
| `config` | object | Iteration, search-result, and page-fetch settings used for the run. |
| `iterations` | list | Ordered LLM loop iterations. |
| `retrievals` | list | Flattened list of every search call and its result payload. |
| `fetches` | list | Flattened list of every model-selected `fetch_page` call when the fetch tool is enabled. |
| `final_response`, `final_answer`, `answered` | string/string/bool | Raw final model response, extracted answer, and abstention-aware answer flag. |
| `ceiling_hit` | bool | True when the loop exhausted the 10-iteration budget without an answer. |
| `total_search_calls` | int | Count of all `search_web` calls. |
| `total_fetch_calls` | int | Count of all `fetch_page` calls. |
| `total_prompt_tokens`, `total_completion_tokens` | int | Token usage summed across all LLM calls. |
| `total_cost_usd` | number | Estimated model plus search cost for the query. |
| `wall_time_seconds` | number | End-to-end query runtime. |
| `errors` | list | Non-fatal loop/tool issues, if any. |

## Iteration Object

Each `iterations[]` entry contains:

| Field | Type | Purpose |
| --- | --- | --- |
| `iteration_num` | int | 1-indexed loop iteration. |
| `llm_request` | object | Full LLM request snapshot before the call, including rendered `messages`, `tools`, provider/model config, temperature, token field, and tool choice. |
| `llm_response` | string | Assistant text content for this turn. |
| `llm_tool_calls` | list | Raw tool calls from Azure OpenAI. |
| `llm_usage` | object | Prompt/completion/total tokens for this call. |
| `llm_latency_ms` | number | LLM latency. |
| `agent_decision` | string | `search`, `fetch`, `tool`, or `answer`. |
| `searches` | list | Search calls made in this iteration. Supports multiple calls per model turn. |
| `fetches` | list | Page fetches made in this iteration when `fetch_page` is enabled. Supports multiple calls per model turn. |

## Retrieval Object

Each `retrievals[]` and `iterations[].searches[]` entry contains:

| Field | Type | Purpose |
| --- | --- | --- |
| `retrieval_id` | string | Stable within-trace retrieval ID. |
| `iteration_num` | int | Parent loop iteration. |
| `tool_call_id` | string | Azure OpenAI tool call ID. |
| `search_query` | string | Exact query passed to the configured search provider. |
| `search_response` | object | Normalized provider response plus raw payload. |

`search_response.results[]` stores `document_id`, `rank`, `title`, `url`, `snippet`, `domain`, and provider metadata. `document_id` is the model-visible stable ID used by `fetch_page`; the runner resolves it back to the URL internally. For Brave, `provider_metadata.extra_snippets` is also rendered into the model prompt as `<extra_snippet>` entries under each document. `search_response.raw_response` keeps the full raw provider payload for later audit and metric changes.

When page fetching is enabled, each result also contains `page_fetch`:

| Field | Type | Purpose |
| --- | --- | --- |
| `artifact_path` | string | Gzip JSON artifact containing the full extracted page record. |
| `fetch_backend` | string | Page fetch backend, currently `local` or `jina`. |
| `reader_url` | string/null | Reader endpoint URL when the `jina` backend is used. |
| `fetch_status` | string | `success`, `empty`, or `failed`. |
| `http_status` | int/null | HTTP response status when available. |
| `content_type` | string/null | HTTP content type. |
| `final_url` | string/null | URL after redirects. |
| `extractor` | string/null | Extraction method, such as `trafilatura`, `stdlib_html_parser`, `plain_text`, `jina_reader_markdown`, or `pdf_unsupported_v1`. |
| `extracted_text_chars` | int | Character count of extracted text. |
| `extracted_text_tokens_estimate` | int | Rough token estimate, currently chars / 4. |
| `text_sha256` | string/null | Hash of extracted text. |
| `extracted_text` | string | Full extracted text included in the model prompt for V1.5 debugging. |

The rendered tool response in `iterations[].llm_request.messages` includes the full extracted page inside `<extracted_page><content>...</content></extracted_page>`, so the trace captures exactly what the model saw.

## Agentic Fetch Mode

When `config.fetch_tool_enabled` is true, `search_web` returns snippet-only search results and the model can call a second tool, `fetch_page`, to open selected URLs. In this mode, automatic page text inclusion in `<search_documents>` is disabled so page-opening behavior is observable.

Each `fetches[]` entry contains:

| Field | Type | Purpose |
| --- | --- | --- |
| `fetch_id` | string | Stable within-trace fetch ID. |
| `iteration_num` | int | Parent loop iteration. |
| `tool_call_id` | string | Azure OpenAI tool call ID. |
| `requested_document_id` | string | Exact model-provided document ID, e.g. `s2r4`. |
| `url` | string | URL resolved internally from `requested_document_id`. |
| `reason` | string | Optional model-provided reason for opening the page. |
| `seen_in_search_results` | bool | Whether the URL exactly matched a previous search result after normalization. |
| `source_retrieval_id`, `source_document_id`, `source_search_query`, `source_rank` | string/string/string/int/null | Search-result provenance when the document ID or URL was previously surfaced. |
| `source_title`, `source_domain`, `source_snippet` | string | Search-result metadata for the fetched URL when available. |
| `page_fetch` | object | Same page-fetch summary schema used by automatic page fetching. |

The rendered `fetch_page` tool response is a `<fetched_page>` XML block containing URL provenance, fetch status, extraction metadata, and extracted text. This lets downstream analysis distinguish smart fetches, foolish fetches, missed useful URLs, and answer-from-snippet behavior.

## Metric Coverage

This schema directly supports:

- Total Search Calls, Ceiling Hit Rate, reformulation rate, redundant search, source diversity, gold document hit, prompt/completion token totals, cost per query, premature termination, and coarse retrieval/reasoning failure mode.
- EM and token F1 using `final_answer` and `gold_answer`.
- STFU, Useful Doc Rank, Retrieval Precision@10, hallucination rate, and LLM-as-judge after adding the planned judge pass over `retrievals[]`, retrieved snippets, `gold_answer`, and `final_answer`.
