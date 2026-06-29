# Task 3 offline fetch-policy ablation

Computed from existing Kimi per-URL judge JSONLs; no provider calls or page fetches were rerun.

Important interpretation notes:

- All policies see the same pre-fetch snippet surface; `snippet_only` therefore captures pre-fetch support with zero fetches.
- Rank-k policies select the lowest-rank distinct URLs in the already observed provider-query trajectory.
- Counterfactual page support is a lower bound: a rank-k policy only gets page-support credit when that URL was actually fetched and page-judged in the observed trace.
- Counterfactual fetch cost uses the observed page token estimate when available and otherwise imputes the provider median observed successful fetch size.
- `oracle_fetch_if_any_support` is a hindsight upper bound that fetches the lowest-rank judged support URL, if any.
- `oracle_fetch_if_needed` is a more cost-minimal hindsight diagnostic: it fetches only when no pre-fetch support exists but an observed page-only support URL exists.

## Main support and budget table

| Policy | Brave support | Tavily support | Firecrawl support | Brave fetch/q | Tavily fetch/q | Firecrawl fetch/q |
|---|---:|---:|---:|---:|---:|---:|
| snippet_only | 30 (30%) | 16 (16%) | 16 (16%) | 0.00 | 0.00 | 0.00 |
| fetch_rank_1 | 30 (30%) | 18 (18%) | 18 (18%) | 1.00 | 1.00 | 1.00 |
| fetch_top_3 | 31 (31%) | 21 (21%) | 18 (18%) | 3.00 | 3.00 | 3.00 |
| fetch_top_5 | 33 (33%) | 24 (24%) | 19 (19%) | 5.00 | 5.00 | 5.00 |
| observed_agent_policy | 33 (33%) | 24 (24%) | 19 (19%) | 1.01 | 1.25 | 1.24 |
| oracle_fetch_if_any_support | 33 (33%) | 24 (24%) | 19 (19%) | 0.33 | 0.24 | 0.19 |
| oracle_fetch_if_needed | 33 (33%) | 24 (24%) | 19 (19%) | 0.03 | 0.08 | 0.03 |

## Efficiency and contamination diagnostics

| Provider | Policy | Incremental page support | Incremental support/fetch | Total support/fetch | Fetch tokens/query | Imputed fetches | Opened contradiction q | Surface contradiction q |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Brave | snippet_only | 0 | -- | -- | 0 | 0 | 0 | 27 |
| Brave | fetch_rank_1 | 0 | 0 | 0.3 | 16,616 | 76 | 11 | 27 |
| Brave | fetch_top_3 | 1 | 0.003 | 0.103 | 44,023 | 254 | 17 | 27 |
| Brave | fetch_top_5 | 3 | 0.006 | 0.066 | 69,093 | 440 | 21 | 27 |
| Brave | observed_agent_policy | 3 | 0.03 | 0.327 | 21,939 | 0 | 9 | 27 |
| Brave | oracle_fetch_if_any_support | 3 | 0.091 | 1 | 4,233 | 27 | 0 | 27 |
| Brave | oracle_fetch_if_needed | 3 | 1 | 11 | 318 | 0 | 0 | 27 |
| Tavily | snippet_only | 0 | -- | -- | 0 | 0 | 0 | 21 |
| Tavily | fetch_rank_1 | 2 | 0.02 | 0.18 | 11,049 | 81 | 7 | 21 |
| Tavily | fetch_top_3 | 5 | 0.017 | 0.07 | 34,082 | 255 | 16 | 21 |
| Tavily | fetch_top_5 | 8 | 0.016 | 0.048 | 56,145 | 431 | 18 | 21 |
| Tavily | observed_agent_policy | 8 | 0.064 | 0.192 | 21,540 | 0 | 8 | 21 |
| Tavily | oracle_fetch_if_any_support | 8 | 0.333 | 1 | 4,340 | 13 | 0 | 21 |
| Tavily | oracle_fetch_if_needed | 8 | 1 | 3 | 1,514 | 0 | 0 | 21 |
| Firecrawl | snippet_only | 0 | -- | -- | 0 | 0 | 0 | 28 |
| Firecrawl | fetch_rank_1 | 2 | 0.02 | 0.18 | 16,279 | 67 | 10 | 28 |
| Firecrawl | fetch_top_3 | 2 | 0.007 | 0.06 | 40,416 | 236 | 20 | 28 |
| Firecrawl | fetch_top_5 | 3 | 0.006 | 0.038 | 60,383 | 423 | 25 | 28 |
| Firecrawl | observed_agent_policy | 3 | 0.024 | 0.153 | 26,575 | 0 | 10 | 28 |
| Firecrawl | oracle_fetch_if_any_support | 3 | 0.158 | 1 | 3,380 | 13 | 0 | 28 |
| Firecrawl | oracle_fetch_if_needed | 3 | 1 | 6.333 | 383 | 0 | 0 | 28 |

## Provider judge totals

| Provider | Valid rows | Snippet rows | Page rows | Invalid rows | Imputed fetch token median |
|---|---:|---:|---:|---:|---:|
| Brave | 2196 | 2095 | 101 | 6 | 11,639 |
| Tavily | 2464 | 2339 | 125 | 17 | 9,629 |
| Firecrawl | 2209 | 2085 | 124 | 17 | 10,287 |
