# Draft Metrics

Preliminary metrics for the optional `fetch_page` architecture. These are intended as working notes for interpreting early runs, not final paper-ready results.

## Brave 100: Optional Fetch With Jina

- Trace: `data/traces/phase1_v1_brave_gpt54_fetch_tool_jina_100.jsonl`
- Run ID: `phase1_fetch_tool_jina_brave_100`
- Provider: Brave
- Model: `azure:gpt-5.4`
- Fetch mode: model-optional `fetch_page(document_id)`
- Fetch backend: Jina Reader markdown
- Query set: `data/queries/phase1_100.json`

### Run Health

| Metric | Value |
| --- | ---: |
| Queries written | 100 / 100 |
| Missing query IDs | 0 |
| Duplicate query IDs | 0 |
| Failed query rows | 0 |
| Answered | 98 |
| Abstained | 2 |
| Search calls | 229 |
| Avg search calls / query | 2.29 |
| Fetch calls | 102 |
| Avg fetch calls / query | 1.02 |
| Queries with at least one fetch | 65 |
| Queries without fetch | 35 |

### Answer And Evidence Metrics

| Metric | Value |
| --- | ---: |
| Exact match | 21 / 100 |
| Average token F1 | 0.270 |
| Gold URL exact hit in search results | 59 / 100 |
| Gold URL prefix hit in search results | 63 / 100 |
| Gold domain hit in search results | 82 / 100 |
| Gold source-family hit in search results | 61 / 100 |
| Gold answer text in any retrieved text | 78 / 100 |
| Gold answer text in snippets | 55 / 100 |
| Gold answer text in extra snippets | 71 / 100 |
| Gold answer text in fetched page text | 52 / 100 |
| Wrong answer despite retrieved answer text available | 57 / 100 |
| Wrong answer without retrieved answer text available | 22 / 100 |

### Fetch And Context Metrics

| Metric | Value |
| --- | ---: |
| Successful fetches | 92 / 102 |
| Failed fetches | 10 / 102 |
| Fetch backend count | `jina`: 102 |
| Extractor count | `jina_reader_markdown`: 92, `none`: 10 |
| Total tokens | 5,962,681 |
| Avg tokens / query | 59,626.81 |
| Median tokens / query | 40,638.5 |
| Max tokens / query | 303,462 |
| Queries over 100k tokens | 19 |
| Median extracted chars | 35,998.5 |
| P90 extracted chars | 266,865 |
| Max extracted chars | 821,513 |
| Fetched pages over 50k chars | 42 |
| Fetched pages over 100k chars | 23 |
| Fetched pages over 500k chars | 3 |

## Early Read

The most interesting signal is not the raw exact-match rate by itself. The sharper finding is the gap between evidence availability and answer accuracy:

- Search often gets near the right evidence: gold domain appears in 82 queries, and gold answer text appears somewhere in retrieved text for 78 queries.
- The model still answers incorrectly in many cases where supporting answer text was retrievable: 57 wrong answers had answer text available somewhere in retrieved material.
- Optional fetching is selective rather than constant: the model fetched on 65 queries and skipped fetching on 35.
- Optional fetching contributes real evidence: fetched page text contains the gold answer on 52 queries.
- Context cost is high and heavy-tailed: 19 queries exceed 100k total tokens, and some fetched pages are very large.

This supports the proposed research angle: retrieval quality is not only a provider ranking problem. It is also a trajectory-control problem involving when the model searches, what it chooses to fetch, and whether it can use the evidence it already has.

## Tavily 100: Optional Fetch With Jina

- Trace: `data/traces/phase1_v1_tavily_gpt54_fetch_tool_jina_100.jsonl`
- Run ID: `phase1_fetch_tool_jina_tavily_100`
- Provider: Tavily
- Model: `azure:gpt-5.4`
- Fetch mode: model-optional `fetch_page(document_id)`
- Fetch backend: Jina Reader markdown
- Query set: `data/queries/phase1_100.json`

The file contains 101 rows because one transient failed search row was preserved and then the same query was rerun successfully. Metrics below use latest-by-query semantics.

### Run Health

| Metric | Value |
| --- | ---: |
| Latest queries | 100 / 100 |
| Trace rows | 101 |
| Missing query IDs | 0 |
| Extra query IDs | 0 |
| Historical failed rows | 1 |
| Latest failed queries | 0 |
| Transient failures recovered | 1 |
| Answered | 97 |
| Abstained | 3 |
| Search calls | 274 |
| Avg search calls / query | 2.74 |
| Fetch calls | 130 |
| Avg fetch calls / query | 1.30 |
| Queries with at least one fetch | 76 |
| Queries without fetch | 24 |

### Answer And Evidence Metrics

| Metric | Value |
| --- | ---: |
| Exact match | 21 / 100 |
| Average token F1 | 0.261 |
| Gold URL exact hit in search results | 57 / 100 |
| Gold URL prefix hit in search results | 62 / 100 |
| Gold domain hit in search results | 82 / 100 |
| Gold source-family hit in search results | 60 / 100 |
| Gold answer text in any retrieved text | 75 / 100 |
| Gold answer text in snippets | 60 / 100 |
| Gold answer text in extra snippets | 0 / 100 |
| Gold answer text in fetched page text | 57 / 100 |
| Wrong answer despite retrieved answer text available | 56 / 100 |
| Wrong answer without retrieved answer text available | 23 / 100 |

### Fetch And Context Metrics

| Metric | Value |
| --- | ---: |
| Successful fetches | 119 / 130 |
| Failed fetches | 11 / 130 |
| Fetch backend count | `jina`: 130 |
| Extractor count | `jina_reader_markdown`: 119, `none`: 11 |
| Total tokens | 5,415,593 |
| Avg tokens / query | 54,155.93 |
| Median tokens / query | 36,867.5 |
| Max tokens / query | 305,474 |
| Queries over 100k tokens | 16 |
| Median extracted chars | 34,232.0 |
| P90 extracted chars | 178,764 |
| Max extracted chars | 821,513 |
| Fetched pages over 50k chars | 43 |
| Fetched pages over 100k chars | 24 |
| Fetched pages over 500k chars | 2 |

### Notable Trajectory Cases

| Query ID | Note |
| --- | --- |
| `sealhard_904abf430fa7` | First Tavily attempt failed during search with `Remote end closed connection without response`; rerun succeeded with 6 searches, 0 fetches, 23,755 tokens. |
| `sealhard_9d5b346b1ad2` | Highest fetch-count Tavily case: 8 fetches, 6 searches, 265,964 tokens. |
| `sealhard_3fdf524a2ea9` | Highest-token Tavily case: 305,474 tokens, 6 searches, 3 fetches. |
| `sealhard_4f507e42c1be` | Abstained after 5 searches, 2 fetches, 80,205 tokens. |
| `sealhard_b6c30f169f85` | Abstained after 4 searches, 1 fetch, 44,552 tokens. |
| `sealhard_e5ddddb8907e` | Abstained after 5 searches, 2 fetches, 101,714 tokens. |

## Firecrawl 100: Optional Fetch With Jina

- Trace: `data/traces/phase1_v1_firecrawl_gpt54_fetch_tool_jina_100.jsonl`
- Run ID: `phase1_fetch_tool_jina_firecrawl_100`
- Provider: Firecrawl
- Model: `azure:gpt-5.4`
- Fetch mode: model-optional `fetch_page(document_id)`
- Fetch backend: Jina Reader markdown
- Query set: `data/queries/phase1_100.json`

### Run Health

| Metric | Value |
| --- | ---: |
| Queries written | 100 / 100 |
| Missing query IDs | 0 |
| Duplicate query IDs | 0 |
| Failed query rows | 0 |
| Answered | 96 |
| Abstained | 4 |
| Search calls | 251 |
| Avg search calls / query | 2.51 |
| Fetch calls | 128 |
| Avg fetch calls / query | 1.28 |
| Queries with at least one fetch | 81 |
| Queries without fetch | 19 |

### Answer And Evidence Metrics

| Metric | Value |
| --- | ---: |
| Exact match | 23 / 100 |
| Average token F1 | 0.282 |
| Gold URL exact hit in search results | 60 / 100 |
| Gold URL prefix hit in search results | 63 / 100 |
| Gold domain hit in search results | 82 / 100 |
| Gold source-family hit in search results | 64 / 100 |
| Gold answer text in any retrieved text | 76 / 100 |
| Gold answer text in snippets | 54 / 100 |
| Gold answer text in extra snippets | 0 / 100 |
| Gold answer text in fetched page text | 61 / 100 |
| Wrong answer despite retrieved answer text available | 53 / 100 |
| Wrong answer without retrieved answer text available | 24 / 100 |

### Fetch And Context Metrics

| Metric | Value |
| --- | ---: |
| Successful fetches | 121 / 128 |
| Failed fetches | 7 / 128 |
| Fetch backend count | `jina`: 128 |
| Extractor count | `jina_reader_markdown`: 121, `none`: 7 |
| Total tokens | 5,797,879 |
| Avg tokens / query | 57,978.79 |
| Median tokens / query | 34,383.5 |
| Max tokens / query | 380,646 |
| Queries over 100k tokens | 16 |
| Median extracted chars | 39,597.0 |
| P90 extracted chars | 241,876 |
| Max extracted chars | 821,513 |
| Fetched pages over 50k chars | 54 |
| Fetched pages over 100k chars | 28 |
| Fetched pages over 500k chars | 3 |

### Notable Trajectory Cases

| Query ID | Note |
| --- | --- |
| `sealhard_b9d6a3303845` | Highest-token Firecrawl case: 380,646 tokens, 3 searches, 3 fetches. |
| `sealhard_509fa8d560e8` | Heavy fetch + token case: 5 fetches, 3 searches, 376,068 tokens. |
| `sealhard_5a4a585bfbac` | Most searches among top-token cases: 9 searches, 5 fetches, 286,186 tokens. |
| `sealhard_85fcb317a706` | Abstained after 7 searches, 2 fetches, 103,109 tokens. |
| `sealhard_b6c30f169f85` | Abstained after 6 searches, 2 fetches, 62,385 tokens. |
| `sealhard_93641f5fc924` | Abstained after 6 searches, 0 fetches, 31,937 tokens. |
| `sealhard_1768d0c92783` | Abstained after 3 searches, 0 fetches, 8,482 tokens. |

## Brave vs Tavily vs Firecrawl Snapshot

| Metric | Brave | Tavily | Firecrawl |
| --- | ---: | ---: | ---: |
| Latest queries | 100 | 100 | 100 |
| Latest failed queries | 0 | 0 | 0 |
| Answered | 98 | 97 | 96 |
| Abstained | 2 | 3 | 4 |
| Exact match | 21 | 21 | 23 |
| Avg token F1 | 0.270 | 0.261 | 0.282 |
| Gold URL exact hit | 59 | 57 | 60 |
| Gold URL prefix hit | 63 | 62 | 63 |
| Gold domain hit | 82 | 82 | 82 |
| Gold source-family hit | 61 | 60 | 64 |
| Gold answer text in any retrieved text | 78 | 75 | 76 |
| Gold answer text in snippets | 55 | 60 | 54 |
| Gold answer text in fetched page text | 52 | 57 | 61 |
| Wrong with answer text available | 57 | 56 | 53 |
| Wrong without answer text available | 22 | 23 | 24 |
| Search calls | 229 | 274 | 251 |
| Avg searches / query | 2.29 | 2.74 | 2.51 |
| Fetch calls | 102 | 130 | 128 |
| Avg fetches / query | 1.02 | 1.30 | 1.28 |
| Queries with fetch | 65 | 76 | 81 |
| Successful fetches | 92 / 102 | 119 / 130 | 121 / 128 |
| Total tokens | 5,962,681 | 5,415,593 | 5,797,879 |
| Avg tokens / query | 59,626.81 | 54,155.93 | 57,978.79 |
| Median tokens / query | 40,638.5 | 36,867.5 | 34,383.5 |
| Max tokens / query | 303,462 | 305,474 | 380,646 |
| Queries over 100k tokens | 19 | 16 | 16 |

Early comparison: Firecrawl produced the top exact-match count (23 vs 21/21) and the highest avg token F1 (0.282), edging Brave and Tavily on the strictest answer metrics. It also reached the most queries with at least one fetch (81 of 100) and the highest fetch success rate (121/128 = 94.5%), and lands more gold answer text in fetched pages than either Brave or Tavily (61 vs 52/57). Search effort sits between the other two (2.51 avg vs Brave 2.29 / Tavily 2.74), and total token usage is in the middle as well. Brave still leads on "answer text anywhere in retrieved context" (78), which suggests its snippets+extra snippets carry more lexical coverage even when the model fetches less. The provider-trajectory split holds: more tool use does not monotonically lift accuracy, but it shifts where the supporting evidence appears — and Firecrawl's higher fetch-success-into-page-evidence pipeline appears to convert slightly more often into a correct answer on this set.

## Caveats

- Exact match is deterministic and strict; it should be treated as a rough automatic metric.
- Answer-text availability is based on normalized string containment. It can overcount when the answer string is ambiguous and undercount paraphrased support.
- `answer_in_page` now includes both old auto-fetched page records and new optional `fetch_page` records. Earlier summaries before this analysis fix undercounted optional fetched page evidence.
- These metrics are not yet document-level LLM judge results.
