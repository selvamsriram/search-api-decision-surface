I’d submit it to **GroundLM 2026**, but I would make a few targeted changes first. It is a good workshop fit: GroundLM explicitly calls for work on RAG, knowledge grounding, factuality/hallucination, and evaluation frameworks for grounding and faithfulness, and it especially encourages strong empirical work, resource papers, and reliability/efficiency framing. ([Groundlm][1]) Your paper’s core claim—that search APIs are not interchangeable retrievers but **decision surfaces** that shape evidence exposure, contradiction, and fetch-budget use—is directly in scope. 

My read: **content-wise, this is already plausible for a workshop acceptance; the approval odds would improve most if you close 4–6 reviewer-objection holes rather than adding more experiments indiscriminately.**

## Biggest fix before submission: separate “pre-fetch surface” from “page-visible evidence”

This is the most important issue. The paper’s central phrase is **decision surface**, meaning the ranked URLs/snippets/metadata the agent sees *before* fetching. But your current “visible support” definition counts support from either snippet-only rows **or page-visible rows**.  That creates a conceptual ambiguity: some “visible support” may only become visible *after* the agent has already decided to fetch, which weakens the decision-surface framing.

I would change the metrics to three clearly named buckets:

| Current ambiguity                              | Better terminology                |
| ---------------------------------------------- | --------------------------------- |
| “Visible support”                              | **Trajectory-visible support**    |
| Support in title/snippet/metadata before fetch | **Pre-fetch surface support**     |
| Support only in fetched page text              | **Post-fetch discovered support** |

Then compute SMART/MISSED/BLIND primarily using **pre-fetch surface support**. Keep the page-visible analysis, but call it “support discovered after fetch.” This one change will make the paper much harder to criticize.

A likely reviewer comment otherwise: *“The decision partition is claimed to characterize pre-fetch action states, but the support variable includes post-fetch page evidence.”* Fixing this is worth more than adding another provider.

## Add a small judge-validation paragraph or table

The paper relies on one Kimi-K2.6 judge for 6,869 valid per-URL judgments, and the limitations already acknowledge the single-agent/single-judge issue.   For GroundLM, where faithfulness and grounding evaluation are central, reviewers will care about judge reliability.

Best quick fix: sample 100–200 URL judgments stratified by provider and label type, then add a compact validation table:

| Label                   | Human/second-judge agreement | Notes                                    |
| ----------------------- | ---------------------------: | ---------------------------------------- |
| contains_gold_answer    |                          xx% | hardest cases: aliases / numeric answers |
| contradicts_gold_answer |                          xx% | hardest cases: outdated pages            |
| is_garbage              |                          xx% | mostly extraction failures               |

If you cannot do human annotation, use a second judge model and call it a **sensitivity check**, not ground truth. Also clarify whether `contains_gold_answer` and `contradicts_gold_answer` were stable when the model’s final answer was removed from the judge prompt, because the judge currently receives the question, gold answer, model final answer, and retrieved document. 

## Add one policy/cost ablation, even if offline

Your conclusion says provider choice is a **policy choice**, and the results show different fetch behavior and token costs across providers.  That claim is strong, but the current paper mostly observes one agent policy rather than testing policies. The limitations also admit the actions are observational rather than randomized. 

A lightweight addition would be an offline “support captured under fetch budget” table:

| Policy                           | Brave | Tavily | Firecrawl |
| -------------------------------- | ----: | -----: | --------: |
| snippet-only support             |       |        |           |
| fetch rank-1                     |       |        |           |
| fetch top-3                      |       |        |           |
| observed agent fetches           |       |        |           |
| oracle fetch among returned URLs |       |        |           |

You do not need to rerun the full agent for this. Use the per-URL labels you already have. This would make the “provider-aware fetch policy” recommendation much more convincing.

## Add uncertainty to the main results, not only the appendix

Right now the headline is compelling: correctness is basically tied at 25/25/26, but support, rank concentration, fetch behavior, and contradiction differ sharply.  However, with only 100 questions, reviewers will ask whether the provider differences are noise.

You already have Wilson intervals for decision-cell correctness in Appendix J.  Move a small amount of uncertainty into the main paper:

* paired bootstrap CIs for visible support differences;
* bootstrap CIs for contradiction-to-gold ratio;
* confidence intervals for fetch-query percentage;
* explicitly say correctness differences are not meaningful/significant.

This will make the paper read as careful rather than overclaiming.

## Normalize or stress-test Brave’s extra snippets

You already disclose that Brave exposes extra provider-native snippet blocks and that this likely affects the visible-support ceiling.  That is honest, but reviewers may still say the comparison is unfair: maybe Brave looks “snippet-rich” simply because it returns more text.

Add one sensitivity analysis:

1. **Drop Brave extra snippets** and recompute visible support / contradiction ratio; or
2. **Normalize by snippet character budget**, e.g., gold-supporting rows per 1k snippet characters; or
3. Explicitly frame the paper as comparing **product surfaces as delivered**, not normalized retrievers.

The third is already your philosophical position, but one quantitative sensitivity would help a lot.

## Make the GroundLM fit explicit in the paper

The workshop title is *Grounding Language Models: Learning Faithfully and Efficiently*, and its CFP emphasizes faithfulness, efficiency, real-world reliability, RAG, knowledge grounding, factuality, hallucination, and grounding evaluation. ([Groundlm][1]) Your current paper fits, but it reads more like agentic search/API evaluation than like a grounding paper.

Add one paragraph in the introduction or discussion:

> For grounded language-model systems, the retrieval API is part of the grounding interface: it determines which evidence is exposed, which contradictions enter context, and how much retrieval budget is spent before an answer is produced. Decision-surface evaluation therefore measures not just retrieval quality, but the faithfulness and efficiency conditions under which grounded answers are generated.

That directly maps your contribution to the workshop’s language.

## Smaller but high-value edits

Rename **“answer-agnostic contradiction-to-gold ratio”** to **“answer-model-independent contradiction-to-gold ratio.”** It is not truly answer-agnostic because it depends on the gold answer; it is independent of the model’s final answer. This is a small terminology change that prevents an easy nitpick. 

Define or remove **F1** in Table 1. The table reports F1 values, but from the current text it is not clear whether this is token-level answer F1, semantic audit F1, or something else. 

Add 1–2 qualitative case studies. The “wrong despite answer text” result is one of the strongest observations: answer text appears somewhere in retrieved text for 78/75/76 provider-query pairs, yet the agent is still wrong in 57/56/53 of those cases.  A concrete trace showing answer text present-but-unused would make the contribution much more memorable.

Move “gold URL exact hit / domain hit / answer in snippet / answer in fetched page” from Appendix J into a compressed main-text table or footnote. It strengthens your argument that ordinary retrieval proxies are insufficient. 

Add run dates and API-version details. Commercial search APIs change. You have request configurations and shared fetch-backend details, but the main paper should state when the searches were run and which provider API versions/settings were used. 

## Submission track recommendation

Submit as **long archival**, not short. GroundLM allows long archival papers up to 8 pages of content with unlimited references; accepted archival papers appear in ACL Anthology proceedings. ([Groundlm][1]) Your main content is already around the right size, and the empirical setup needs room. The official GroundLM direct-submission deadline is listed as June 29, 2026 AoE, with ARR commitment later on August 5, 2026 AoE. ([Groundlm][1])

## Bottom line

I would not spend the remaining time adding many more providers. I would prioritize, in this order:

1. split pre-fetch vs post-fetch support;
2. add judge validation or second-judge sensitivity;
3. add one offline fetch-policy/cost table;
4. add uncertainty/bootstraps to main results;
5. add Brave extra-snippet sensitivity;
6. add explicit GroundLM/faithfulness/efficiency framing.

After those changes, I’d view this as a **strong workshop submission** rather than merely a plausible one.

[1]: https://groundlm.github.io/grouplm_emnlp2026/ "GroundLM 2026 | EMNLP 2026 Workshop"
