# Proposal: Search APIs As Retrieval-Budget Decision Surfaces

## 1. Research Frame

The central question for the next phase is:

> How do commercial search API result surfaces change what an LLM agent chooses to read, ignore, search next, answer from, or abstain on?

The study should move from automatic page fetching to an explicitly agentic retrieval architecture:

```text
search_web(query)
  -> returns provider snippets, titles, URLs, domains, and provider metadata only

fetch_page(url)
  -> fetches/extracts the full page text for one selected URL

At every inference step, the model may:
  -> search_web one or more times
  -> fetch_page one or more times
  -> answer
  -> abstain
```

This turns the search provider from a static ranked-list component into a decision surface. The provider's snippets, rankings, domains, URLs, and metadata shape whether the model spends retrieval budget on opening pages, searches again, answers too early, or gives up.

The key paper claim should not be:

> Different search APIs return different results.

That is obvious.

The useful claim is:

> Search APIs change the agent's retrieval-budget allocation policy: which pages it opens, when it trusts snippets, when it searches again, how much evidence it acquires, and how much cost it spends per supported answer.

This framing is more useful than a provider leaderboard. It is a mechanism study of how search-result surfaces influence downstream agent behavior.

## 2. Why This Is Distinct From BrowseComp

BrowseComp asks whether web-browsing agents can answer hard-to-find questions. Our study should not compete on that axis.

Our differentiating question is:

> Given the same question, same model, same prompt, and same tool interface, how does the search API alter the agent's retrieval trajectory and page-opening decisions?

Important distinctions:

| Dimension | Browse-style hard browsing benchmark | This study |
| --- | --- | --- |
| Main object | Agent capability on hard web QA | Retrieval-budget behavior induced by search APIs |
| Independent variable | Agent/model/system | Search provider result surface |
| Core action | Browse/search until answer | Decide whether to search, fetch, answer, or abstain |
| Primary metrics | Accuracy and browsing success | Useful fetch rate, missed useful URL rate, premature snippet answer rate, trajectory divergence, cost per supported answer |
| Practical output | Hard benchmark | Design rules for search-agent retrieval policy and provider routing |

The research is valuable only if it produces actionable diagnostics:

- when snippets are enough
- when snippets induce premature answers
- when a provider returns good snippets but poor/fetch-hostile URLs
- when the model misses useful URLs that were visible in search results
- when automatic top-k fetching wastes context compared with agentic fetching
- when agentic fetching saves tokens but loses evidence
- when provider choice changes cost/reliability more than final accuracy

## 3. Proposed Agent Architecture

### Tool 1: `search_web`

Input:

```json
{
  "query": "string"
}
```

Output:

```xml
<search_documents>
  <search query="..." provider="brave">
    <document rank="1">
      <title>...</title>
      <url>...</url>
      <domain>...</domain>
      <snippet>...</snippet>
      <extra_snippet>...</extra_snippet>
      <provider_metadata>...</provider_metadata>
    </document>
  </search>
</search_documents>
```

Important rule:

`search_web` should not include extracted page text in the main agentic-fetch condition. It should expose only the search API result surface.

### Tool 2: `fetch_page`

Input:

```json
{
  "url": "https://example.com/page",
  "reason": "optional short reason for opening this page"
}
```

Output:

```xml
<fetched_page>
  <url>...</url>
  <final_url>...</final_url>
  <fetch_status>success | empty | failed</fetch_status>
  <http_status>...</http_status>
  <content_type>...</content_type>
  <extractor>trafilatura | stdlib_html_parser | pdf_unsupported_v1 | ...</extractor>
  <extracted_text_chars>...</extracted_text_chars>
  <content>
    Extracted page text...
  </content>
</fetched_page>
```

The model may fetch any URL it has seen in prior search results. The trace should record whether fetched URLs came from the most recent search result, an earlier result, or a model-invented URL. The default should probably reject or separately label URLs that were not previously surfaced by `search_web`, to keep provider attribution clean.

### Agent Decision Space

At each turn, the model can:

- call `search_web`
- call `fetch_page`
- call multiple tools in one turn when supported
- answer with `FINAL ANSWER: ...`
- abstain with `FINAL ANSWER: I cannot determine the answer from available sources.`

This architecture exposes a previously hidden behavior: page-opening policy.

## 4. Experimental Design

### Main Conditions

Run the same 100-query Phase 1 SEAL-HARD sample across three providers:

- Brave
- Tavily
- Firecrawl

Use the same model, prompt, max iteration budget, max search results, page fetcher, and answer format.

### Architecture Conditions

The strongest study should compare three retrieval architectures:

| Condition | Search result content | Page fetching | Research purpose |
| --- | --- | --- | --- |
| snippet-only | snippets, URLs, metadata | unavailable | Measures what snippets alone induce |
| auto-fetch top-k | snippets plus automatic fetched text for top-k results | automatic | Current baseline; measures context-heavy retrieval |
| agentic-fetch | snippets first; model chooses `fetch_page` | model-controlled | Main condition; measures retrieval-budget allocation |

The current traces are the `auto-fetch top-3` baseline:

| Provider | Model | Search results per call | Page fetch | Trace |
| --- | --- | ---: | --- | --- |
| Brave | Azure GPT-5.4 | 3 | automatic | `data/traces/phase1_v1_brave_gpt54_top3_pagefetch_phase1_100.jsonl` |
| Tavily | Azure GPT-5.4 | 3 | automatic | `data/traces/phase1_v1_tavily_gpt54_top3_pagefetch_phase1_100.jsonl` |
| Firecrawl | Azure GPT-5.4 | 3 | automatic | `data/traces/phase1_v1_firecrawl_gpt54_top3_pagefetch_phase1_100.jsonl` |

Visible baseline signals:

| Metric | Brave | Tavily | Firecrawl |
| --- | ---: | ---: | ---: |
| exact match | 21 / 100 | 22 / 100 | 22 / 100 |
| answered | 95 / 100 | 98 / 100 | 96 / 100 |
| gold URL prefix hit | 47 / 100 | 34 / 100 | 51 / 100 |
| avg search calls | 2.21 | 2.55 | 2.31 |
| avg source diversity | 3.56 | 4.60 | 4.00 |
| median snippet chars | 244 | 799 | 148 |
| median total tokens | 34,025 | 24,104 | 24,289 |
| avg total tokens | 49,228 | 84,752 | 44,431 |
| max total tokens | 602,701 | 1,768,647 | 397,227 |

These results motivate the new architecture. Automatic page fetching shows that providers create different snippet lengths, URL pools, extraction failures, and token tails, but it does not reveal whether a model would have chosen to open those pages.

### Counterfactual / Replay Conditions

After the main agentic-fetch runs, add smaller diagnostic conditions:

1. **Same first query, different provider results**
   - Use the same model-generated first query.
   - Send it to all providers.
   - Feed each provider's snippet-only result set to the same model state.
   - Compare next action: answer, fetch, search again, or abstain.

2. **Provider result replay**
   - Take one provider's search results and replay them into a fixed agent state.
   - Measure whether later trajectory changes are due to result surface rather than stochastic first-query variation.

3. **Fetch policy oracle**
   - Independently fetch and judge all URLs shown in `search_web` results, whether or not the model chose to open them.
   - Label which visible results contained gold-supporting evidence, model-answer-supporting evidence, contradictory evidence, or garbage.
   - Compare model's fetched URLs to this oracle useful-URL set.
   - This lets us measure whether the model was smart or foolish in its fetch decisions: did it open useful pages, skip useful pages, or waste budget on useless pages?

These diagnostics make the causal story stronger without replacing the main agentic run.

## 5. Primary Metrics

### Retrieval Budget Metrics

| Metric | Meaning |
| --- | --- |
| `search_calls_per_query` | how often the model searches |
| `fetch_calls_per_query` | how often the model opens pages |
| `search_to_fetch_ratio` | exploration vs exploitation |
| `answer_without_fetch_rate` | answers made from snippets only |
| `answer_after_fetch_rate` | answers made after at least one page open |
| `abstain_after_fetch_rate` | pages opened but still insufficient |
| `fetch_rank_distribution` | which result ranks the model opens |
| `fetched_domain_distribution` | domains the model chooses to inspect |
| `repeated_fetch_rate` | duplicate or near-duplicate URL opens |
| `search_again_after_fetch_rate` | how often fetched pages fail to satisfy evidence need |

### Evidence Acquisition Metrics

| Metric | Meaning |
| --- | --- |
| `useful_fetch_rate` | fetched pages that contain gold-supporting evidence / fetched pages |
| `model_answer_support_fetch_rate` | fetched pages supporting the model answer / fetched pages |
| `contradictory_fetch_rate` | fetched pages contradicting the gold answer / fetched pages |
| `garbage_fetch_rate` | fetched pages judged mostly unreadable or valueless / fetched pages |
| `visible_support_rate` | search-result URLs whose independently fetched content supports the gold answer / visible search-result URLs |
| `first_useful_fetch_step` | first turn where useful evidence is fetched |
| `first_useful_fetch_rank` | rank of first useful fetched result |
| `missed_useful_url_rate` | useful URL appeared in search results but was not fetched |
| `fetched_support_hit` | at least one fetched page supports the gold answer |
| `snippet_support_without_fetch` | snippet surface already supported the gold answer, but page was not opened |
| `oracle_fetch_recall` | useful visible URLs fetched by the model / useful visible URLs |
| `oracle_fetch_precision` | useful fetched URLs / all fetched URLs |
| `foolish_fetch_rate` | fetched URLs judged garbage, irrelevant, or unsupported / fetched URLs |
| `smart_skip_rate` | skipped URLs judged garbage, irrelevant, or unsupported / skipped visible URLs |

The most important metrics are:

```text
useful_fetch_rate
missed_useful_url_rate
oracle_fetch_precision
oracle_fetch_recall
```

They reveal whether the agent is spending retrieval budget well.

This requires an offline oracle pass that fetches and judges visible search-result URLs regardless of model choice. The agent's online behavior should remain unchanged: it only sees fetched pages it selected. The oracle pass is for evaluation, letting us construct a confusion matrix over visible results:

| | Oracle useful | Oracle not useful |
| --- | ---: | ---: |
| Model fetched | smart fetch | foolish fetch |
| Model skipped | missed useful URL | smart skip |

This matrix is the cleanest way to evaluate page-opening policy.

### Premature Answer Metrics

| Metric | Meaning |
| --- | --- |
| `premature_snippet_answer_rate` | model answers without fetching when no prompt-visible snippet fully supports the answer |
| `snippet_supported_answer_rate` | answer is supported by snippets alone |
| `wrong_answer_with_unfetched_support` | a useful URL was in search results, but the model failed to fetch it |
| `wrong_answer_after_fetching_wrong_page` | model fetched pages, but not the useful one |
| `over_fetch_rate` | model fetched after sufficient evidence was already visible |

### Cost And Context Metrics

| Metric | Meaning |
| --- | --- |
| `prompt_tokens_per_correct` | token cost per exact answer |
| `prompt_tokens_per_supported_answer` | token cost per evidence-supported answer |
| `fetch_tokens_per_query` | extracted text introduced by `fetch_page` |
| `wasted_fetch_tokens` | fetched text from pages judged garbage or irrelevant |
| `large_fetch_rate` | opened pages above thresholds such as 50k/100k/500k chars |
| `cost_per_useful_fetch` | total model/search/fetch cost per useful page opened |

This is where the new architecture can produce practical design rules. Automatic top-k fetching may increase evidence availability but creates large token tails. Agentic fetching may reduce context cost but miss useful evidence.

### Trajectory Metrics

| Metric | Meaning |
| --- | --- |
| `post_first_search_divergence` | path divergence after providers return first result set |
| `tool_sequence_pattern` | search-search-fetch-answer, search-fetch-search-answer, etc. |
| `fetch_after_rank1_rate` | tendency to open top result immediately |
| `skip_top_rank_rate` | model bypasses top-ranked result for lower-ranked URL |
| `query_refinement_after_bad_fetch` | whether failed fetches lead to better follow-up queries |
| `site_restricted_search_rate` | use of `site:` after provider result exposure |
| `quoted_search_rate` | phrase matching / entity narrowing behavior |

## 6. LLM Judge Layer

The document-level judge remains document-level. It should evaluate a single retrieved or fetched document using the exact prompt-visible document XML.

Current v2 schema:

```json
{
  "contains_gold_answer": true,
  "supports_model_answer": false,
  "contradicts_gold_answer": false,
  "is_garbage": false,
  "garbage_reason": "",
  "answer_span": "short verbatim span from the document",
  "confidence": 0.92
}
```

Definitions:

- `contains_gold_answer`: the document contains enough evidence to answer the question with the gold answer. This is not string matching.
- `supports_model_answer`: the document supports the model's final answer, especially when the model answer differs from gold.
- `contradicts_gold_answer`: the document asserts facts that conflict with the gold answer or would lead to a different answer.
- `is_garbage`: the document content is mostly human-unreadable, blocked, empty, extraction debris, boilerplate, unsupported binary/PDF content with no useful visible snippet evidence, or otherwise valueless.
- `answer_span`: a short verbatim span supporting either the gold or model answer.

Derived document and query metrics:

- `supporting_doc_hit`
- `supporting_doc_hit@k`
- `fetched_supporting_doc_hit`
- `unfetched_supporting_doc_available`
- `model_answer_supported_by_fetched_doc`
- `contradictory_doc_fetched`
- `garbage_doc_fetched`
- `useful_url_seen_but_not_fetched`
- `oracle_fetch_precision`
- `oracle_fetch_recall`
- `smart_fetch_count`
- `foolish_fetch_count`
- `missed_useful_url_count`
- `smart_skip_count`

For the agentic-fetch condition, judge both:

1. every result document shown by `search_web`, whether or not the model opened it, to estimate the oracle useful-URL set
2. every document actually opened by `fetch_page`, to estimate fetch quality and support actually available to the model

If cost requires a cap, the cap should be explicit and rank-based, for example all visible results up to rank 5 per search call. The preferred setup for the 100-query phase is to judge all visible result URLs because the provider top-k is small.

## 7. Core Hypotheses

### Hypothesis 1: Snippet richness changes fetch policy.

Tavily's longer snippets may reduce page opens or delay fetching. This can help when snippets are sufficient, but it can also increase premature snippet answers when snippets are incomplete, stale, or misleading.

Metrics:

- `answer_without_fetch_rate`
- `premature_snippet_answer_rate`
- `fetch_calls_per_query`
- `snippet_supported_answer_rate`

### Hypothesis 2: Source alignment and fetchability are separate from snippet usefulness.

A provider may return canonical or gold-aligned URLs with sparse snippets, while another may return helpful snippets attached to pages that are hard to fetch or not authoritative.

Metrics:

- `gold_url_prefix_hit`
- `fetched_supporting_doc_hit`
- `garbage_fetch_rate`
- `missed_useful_url_rate`
- `fetch_success_rate_by_provider`

### Hypothesis 3: Agentic fetching reduces context cost but creates missed-evidence failures.

Compared with auto-fetch top-k, agentic fetching should lower token usage and reduce prompt bloat. The risk is that the model fails to open the URL that contains the needed evidence.

Metrics:

- `prompt_tokens_per_supported_answer`
- `large_fetch_rate`
- `useful_fetch_rate`
- `missed_useful_url_rate`
- `wrong_answer_with_unfetched_support`

### Hypothesis 4: Provider choice changes exploration vs exploitation.

Some providers may cause the model to search again rather than fetch; others may cause it to open top-ranked pages immediately.

Metrics:

- `search_to_fetch_ratio`
- `fetch_after_rank1_rate`
- `skip_top_rank_rate`
- `search_again_after_fetch_rate`
- `post_first_search_divergence`

### Hypothesis 5: The main value of provider choice may be behavior/cost/reliability, not final EM.

The current baseline already shows similar EM across providers. The new study should test whether provider effects are larger in retrieval-budget allocation and support acquisition than in exact-answer accuracy.

Metrics:

- EM/F1
- `supported_answer_rate`
- `useful_fetch_rate`
- `garbage_fetch_rate`
- `prompt_tokens_per_supported_answer`
- provider transient failure rate

## 8. Failure Taxonomy

The agentic-fetch architecture supports a more useful failure taxonomy:

| Failure mode | Meaning |
| --- | --- |
| `search_surface_failure` | useful URL never appeared in search results |
| `snippet_misleading_failure` | snippet led model toward wrong answer or wrong fetch |
| `missed_fetch_failure` | useful URL appeared but model did not fetch it |
| `foolish_fetch_failure` | model spent fetch budget on pages the oracle judged useless or garbage while useful URLs were visible |
| `bad_fetch_selection_failure` | model fetched irrelevant or garbage pages |
| `fetch_failure` | selected URL failed to fetch |
| `extraction_failure` | selected URL fetched but produced empty/garbage text |
| `premature_snippet_answer` | model answered from snippets without enough support |
| `over_fetching` | model fetched despite sufficient prompt-visible evidence |
| `over_searching` | model kept searching despite sufficient evidence |
| `reasoning_failure_after_support` | useful fetched support existed but final answer was wrong |
| `over_abstention` | useful support existed but model abstained |

This taxonomy is more actionable than a pure retrieval-vs-reasoning split.

## 9. Analysis Plan

### Step 1: Implement Agentic Fetch

Add `fetch_page` as a second tool. `search_web` should return snippets and URLs only in the main condition. The trace schema must record:

- every `search_web` call
- every returned result
- every `fetch_page` call
- whether fetched URL was previously surfaced
- fetched result rank when known
- fetch/extraction metadata
- rendered tool responses
- full tool sequence
- final answer and abstention state

### Step 2: Run Small Smoke Tests

Run 3-5 queries across all providers. Manually inspect traces to verify:

- search results do not include page text
- `fetch_page` output includes extracted text
- model can search, fetch, search again, and answer
- tool-call ordering is preserved
- duplicate URL fetches are handled
- failed/empty fetches are visible to the model

### Step 3: Run Main 100-Query Matrix

For each provider:

- snippet-only
- auto-fetch top-k baseline, using existing traces where possible
- agentic-fetch

Keep model, prompt, temperature, iteration budget, top-k, page fetcher, and dataset fixed.

### Step 4: Run Document Judge

Judge:

- all fetched documents
- all visible search-result documents, whether fetched or skipped, to build the oracle useful-URL set
- all documents in disagreement and failure cases

Use the v2 document-level schema.

Then join each judged visible URL with the model's online action:

| Model action | Judge label | Interpretation |
| --- | --- | --- |
| fetched | gold-supporting | smart fetch |
| fetched | model-answer-supporting but not gold-supporting | misleading or partial fetch |
| fetched | garbage/irrelevant | foolish fetch |
| skipped | gold-supporting | missed useful URL |
| skipped | garbage/irrelevant | smart skip |

This is the core analysis for whether the model's fetch choices were good.

### Step 5: Build Provider And Architecture Comparison Tables

Aggregate by:

- provider
- architecture condition
- topic
- freshness
- `search_results` label: conflicting vs unhelpful
- question type
- answer outcome
- failure mode

### Step 6: Case Studies

Select cases where:

- snippets caused correct answer without fetch
- snippets caused premature wrong answer
- useful URL appeared but was not fetched
- model fetched a misleading page
- provider returned fetch-hostile URLs
- agentic fetch saved large token cost versus auto-fetch
- auto-fetch succeeded but agentic fetch failed
- agentic fetch succeeded while auto-fetch drowned model in noise

## 10. Expected Findings

Likely paper-facing findings:

1. Final EM may stay similar across providers, while fetch policy changes substantially.
2. Snippet-rich providers can reduce fetching but increase premature snippet-answer risk.
3. Automatic top-k fetching improves evidence exposure but creates provider-specific token tails.
4. Agentic fetching reduces context cost but introduces missed-useful-URL failures.
5. Search providers differ not only in ranking quality, but in how easy their results are for a model to triage.
6. Fetchability and evidence usefulness are distinct axes: a provider can return plausible URLs that are poor opened documents.
7. Useful search-agent evaluation needs trajectory and budget metrics, not only answer accuracy or top-k URL relevance.

## 11. Main Contributions

The paper should claim:

1. **A retrieval-budget evaluation framework** for search-augmented LLM agents with explicit search and page-fetch actions.
2. **An empirical study of commercial search APIs as decision surfaces**, showing how provider snippets, rankings, domains, and fetchability alter page-opening behavior and downstream evidence acquisition.
3. **A failure taxonomy for agentic retrieval**, separating search-surface failure, missed-fetch failure, fetch/extraction failure, premature snippet answering, over-fetching, over-searching, and reasoning failure after support.
4. **Design guidance for search-agent builders**, including when to use snippets only, when to auto-fetch, when to let the model fetch, and when to route across providers.

## 12. Suggested Paper Structure

1. Introduction: Search APIs shape not just what agents know, but what agents choose to read.
2. Related Work: Browse-style web QA, retrieval evaluation, search agents, tool-use agents.
3. Agentic Fetch Setup: `search_web`, `fetch_page`, dataset, providers, model, trace schema.
4. Metrics: Retrieval budget, evidence acquisition, premature answers, cost/context, trajectory divergence.
5. Results: Provider x architecture comparison.
6. Failure Analysis: Missed fetches, bad fetches, garbage pages, snippet-induced errors.
7. Case Studies: Concrete trajectories showing provider-induced behavior differences.
8. Design Implications: Provider routing, fetch policies, quality gates, cost controls.
9. Limitations: 100 queries, one model, three providers, one fetcher, judge calibration.
10. Future Work: More models, more providers, policy learning for fetch decisions.

## 13. Best Title Candidates

- Search APIs as Retrieval-Budget Decision Surfaces for LLM Agents
- What Should an Agent Read? Search APIs and Page-Opening Policy in Web QA
- Same Query, Different Reading: How Search APIs Shape LLM Agent Fetch Decisions
- Beyond Search Accuracy: Evaluating Retrieval-Budget Allocation in Web-Augmented Agents
- Search, Fetch, or Answer: Provider-Induced Retrieval Trajectories in LLM Agents

The most direct title is:

> Search, Fetch, or Answer: How Search APIs Shape LLM Agent Retrieval Budgets

## 14. Immediate Next Work

1. Implement `fetch_page` as a second model tool.
2. Add a snippet-only `search_web` rendering mode.
3. Extend traces with fetch tool calls, fetched URL rank, and tool sequence summaries.
4. Add duplicate fetch detection and previously-seen-URL attribution.
5. Run 3-query smoke tests across Brave, Tavily, and Firecrawl.
6. Add deterministic trajectory metrics: search/fetch counts, answer-without-fetch, fetch rank distribution, duplicate fetches.
7. Add an offline oracle fetch/judge pass over all visible search-result URLs, independent of whether the model fetched them.
8. Run v2 document judge on fetched docs and all visible search-result docs for fetch-policy precision/recall.
9. Run the 100-query provider x architecture matrix.
10. Build architecture comparison artifacts:
   - snippet-only vs auto-fetch top-k
   - auto-fetch top-k vs agentic-fetch
   - provider comparison inside agentic-fetch
11. Write case studies around smart fetches, foolish fetches, missed useful URLs, premature snippet answers, and token savings.

## 15. Expected Research Contribution

The likely contribution is not:

> Provider A is better than Provider B.

The stronger contribution is:

> Search API result surfaces change how LLM agents allocate retrieval budget. Providers alter whether the model trusts snippets, opens pages, searches again, answers prematurely, or abstains. These effects can be larger and more practically important than final exact-match differences.

This is the most valuable direction because it turns the research into guidance for real agent design:

- whether to expose page fetch as a model-controlled tool
- whether to auto-fetch top-k pages
- which provider surfaces induce useful vs wasteful fetches
- how to detect premature snippet answers
- how to reduce token blowups without losing evidence
- how to evaluate search providers for agentic systems rather than static retrieval

The paper should therefore argue for evaluating:

```text
provider result surface
  -> model search/fetch/answer policy
  -> evidence acquired
  -> answer support
  -> cost and reliability
```

not only:

```text
provider
  -> top-k relevance
  -> final answer accuracy
```
