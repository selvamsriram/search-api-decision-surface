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
| `config` | object | Iteration and search-result caps used for the run. |
| `iterations` | list | Ordered LLM loop iterations. |
| `retrievals` | list | Flattened list of every search call and its result payload. |
| `final_response`, `final_answer`, `answered` | string/string/bool | Raw final model response, extracted answer, and abstention-aware answer flag. |
| `ceiling_hit` | bool | True when the loop exhausted the 10-iteration budget without an answer. |
| `total_search_calls` | int | Count of all `search_web` calls. |
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
| `agent_decision` | string | `search` or `answer`. |
| `searches` | list | Search calls made in this iteration. Supports multiple calls per model turn. |

## Retrieval Object

Each `retrievals[]` and `iterations[].searches[]` entry contains:

| Field | Type | Purpose |
| --- | --- | --- |
| `retrieval_id` | string | Stable within-trace retrieval ID. |
| `iteration_num` | int | Parent loop iteration. |
| `tool_call_id` | string | Azure OpenAI tool call ID. |
| `search_query` | string | Exact query passed to the configured search provider. |
| `search_response` | object | Normalized provider response plus raw payload. |

`search_response.results[]` stores `rank`, `title`, `url`, `snippet`, `domain`, and provider metadata. For Brave, `provider_metadata.extra_snippets` is also rendered into the model prompt as `<extra_snippet>` entries under each document. `search_response.raw_response` keeps the full raw provider payload for later audit and metric changes.

## Metric Coverage

This schema directly supports:

- Total Search Calls, Ceiling Hit Rate, reformulation rate, redundant search, source diversity, gold document hit, prompt/completion token totals, cost per query, premature termination, and coarse retrieval/reasoning failure mode.
- EM and token F1 using `final_answer` and `gold_answer`.
- STFU, Useful Doc Rank, Retrieval Precision@10, hallucination rate, and LLM-as-judge after adding the planned judge pass over `retrievals[]`, retrieved snippets, `gold_answer`, and `final_answer`.
