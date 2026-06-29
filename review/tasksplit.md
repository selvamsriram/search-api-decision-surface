Below is the review converted into **clear implementation tasks**. I’m grounding these against the current draft, where the paper already defines the decision-surface framing, per-URL Kimi judge, visible support, decision partition, and provider-profile results. 

# Task 1 — Split “visible support” into pre-fetch and post-fetch support

**Priority:** Critical
**Goal:** Remove the main conceptual weakness in the paper.

Right now, the paper argues that search APIs are **pre-fetch decision surfaces**, but the metric “visible support” includes support from both snippets and fetched page text. That lets a reviewer say: “You are calling this a pre-fetch surface, but some of your support is only visible after fetching.”

## What to do

Create three support variables:

```text
pre_fetch_surface_support
```

Gold answer appears in the URL/title/snippet/metadata surface before any fetch.

```text
post_fetch_discovered_support
```

Gold answer appears only after the agent fetches a page.

```text
trajectory_visible_support
```

Gold answer appears anywhere the agent saw it during the trajectory, either before fetch or after fetch.

## Required changes

Update the metric definitions section.

Replace the current “Visible support” definition with something like:

> We distinguish pre-fetch surface support from post-fetch discovered support. Pre-fetch surface support exists when a valid snippet-only judgment marks `contains_gold_answer` or `gold_answer_in_snippets` true. Post-fetch discovered support exists when a page-visible judgment marks `gold_answer_in_extracted_page` true but no pre-fetch support was present for that provider-query pair. Trajectory-visible support is their union.

Update Figure 3 / decision partition to use **pre-fetch support** as the default.

The decision cells should become:

```text
SMART: pre-fetch support exists and the agent fetched a support-bearing URL
MISSED: pre-fetch support exists but the agent did not fetch support
BLIND: no pre-fetch support exists but the agent fetched
NO-OP: no pre-fetch support exists and no fetch
```

Keep the old union metric only as a secondary diagnostic called **trajectory-visible support**.

## Deliverables

1. Updated script producing the three support counts.
2. Updated Table 2 with separate rows for:

   * Pre-fetch support
   * Post-fetch discovered support
   * Trajectory-visible support
3. Updated Figure 3 using pre-fetch support.
4. Updated Appendix A formal definitions.

## Acceptance criteria

A reviewer should no longer be able to say that the paper confuses “decision surface” with evidence seen after the fetch. The main analysis must be about **what the agent knew before deciding to fetch**.

---

# Task 2 — Add judge validation or second-judge sensitivity

**Priority:** Critical
**Goal:** Defend the Kimi-K2.6 per-URL oracle.

The paper currently depends heavily on one LLM judge labeling 6,869 valid URL-level rows. That is fine for a workshop paper, but reviewers will ask whether the judge labels are reliable.

## What to do

Run a validation pass on a small stratified sample of judged rows.

Sample size:

```text
100 minimum
200 better
```

Stratify by:

```text
provider: Brave / Tavily / Firecrawl
surface type: snippet-only / page-visible
label type: contains_gold_answer / contradicts_gold_answer / is_garbage
```

Then validate using either:

Option A, best:

```text
Human audit by you
```

Option B, acceptable:

```text
Second-judge model sensitivity check
```

Option C, fastest:

```text
Human audit of only high-impact rows:
support=true, contradiction=true, and rows that determine SMART/MISSED/BLIND assignment
```

## Required output table

Add a compact table like:

| Label                   | Sampled rows | Agreement | Main disagreement pattern         |
| ----------------------- | -----------: | --------: | --------------------------------- |
| contains_gold_answer    |           80 |       xx% | aliases / formatting variants     |
| contradicts_gold_answer |           60 |       xx% | outdated pages / partial conflict |
| is_garbage              |           60 |       xx% | media pages / extraction failures |

## Required text

Add a subsection in Section 4 or Appendix F:

> To assess judge sensitivity, we audited a stratified sample of URL judgments. Agreement was highest for garbage labels and lower for contradiction labels, where disagreements mostly involved partial or outdated evidence. The main provider-level conclusions were unchanged under this audit.

## Deliverables

1. `judge_validation_sample.csv`
2. `judge_validation_results.csv`
3. One validation table in the paper.
4. Short paragraph in Section 4 or Limitations.

## Acceptance criteria

The paper should no longer look like it blindly trusts one LLM judge. It should show that the judge is an audit instrument with some validation.

---

# Task 3 — Add an offline fetch-policy / budget ablation

**Priority:** High
**Goal:** Make the claim “provider choice is a policy choice” empirically stronger.

The discussion currently says different providers reward different policies: Tavily rewards top-result fetching, Brave rewards snippet use, and Firecrawl induces broader exploration. That is a strong claim, but the current experiment mostly observes the one GPT-5.4 agent policy.

## What to do

Using existing per-URL labels, simulate simple offline policies without rerunning the agent.

Policies to compute:

```text
snippet_only
fetch_rank_1
fetch_top_3
fetch_top_5
observed_agent_policy
oracle_fetch_if_any_support
```

For each provider, compute:

```text
support captured
fetches used
support per fetch
estimated fetch-token cost
contradiction exposure
```

## Table to add

| Policy         | Brave support captured | Tavily support captured | Firecrawl support captured | Avg fetches/query |
| -------------- | ---------------------: | ----------------------: | -------------------------: | ----------------: |
| snippet only   |                        |                         |                            |                 0 |
| fetch rank 1   |                        |                         |                            |                 1 |
| fetch top 3    |                        |                         |                            |                 3 |
| observed agent |                        |                         |                            |          observed |
| oracle fetch   |                        |                         |                            |          variable |

## Why this matters

This turns the paper from:

> Providers behave differently.

into:

> Because providers behave differently, the optimal fetch policy changes.

That is much more useful for GroundLM reviewers because it connects grounding quality to efficiency.

## Deliverables

1. New script or script mode: `policy_ablation.py`
2. New table in Results or Discussion.
3. Short paragraph interpreting the result.
4. Optional appendix table with more policy variants.

## Acceptance criteria

The paper should be able to support a sentence like:

> Under the same offline fetch budget, providers expose different amounts of gold support, showing that search API selection and fetch policy must be jointly tuned.

---

# Task 4 — Add uncertainty estimates to the main results

**Priority:** High
**Goal:** Avoid overclaiming from 100 questions.

The paper has only 100 questions. That is okay for a workshop if the paper is careful, but the main claims should include uncertainty.

## What to do

Add bootstrap or paired-bootstrap confidence intervals for the most important provider differences.

Metrics needing uncertainty:

```text
correct / 100
pre-fetch support
rank-1 gold concentration
contradiction-to-gold ratio
fetch rate
tokens/query
decision-cell correctness
```

Best method:

```text
paired bootstrap over question IDs
```

Why paired? Because every question is run through all three providers. Resampling questions preserves the matched comparison.

## Main paper changes

In Table 1 or Table 2, either add CIs directly or add a compact note:

> Differences in final correctness are not meaningful under paired bootstrap intervals, while pre-fetch support and contradiction exposure show larger provider-level separation.

In Appendix J, add full CI tables.

## Deliverables

1. Bootstrap script.
2. Main paper summary of uncertainty.
3. Appendix CI table.
4. Updated captions saying which differences are descriptive vs robust.

## Acceptance criteria

The paper should not read like “Brave is definitely better” or “Firecrawl is definitely worse.” It should read like:

> Correctness is statistically indistinguishable at this scale, but evidence-surface diagnostics differ enough to motivate provider-aware policy design.

---

# Task 5 — Normalize or stress-test Brave’s extra snippets

**Priority:** High
**Goal:** Prevent the “unfair comparison” objection.

The paper already says Brave exposes extra provider-native snippet blocks. That is honest, but a reviewer may say Brave’s visible-support advantage is just because Brave returns more pre-fetch text.

## What to do

Run one sensitivity analysis.

Choose one of these:

### Option A — Drop Brave extra snippets

Recompute:

```text
pre_fetch_surface_support
rank_1_gold_rows
contradiction_to_gold_ratio
decision partition
```

with Brave’s `extra_snippets` removed.

### Option B — Normalize by snippet text budget

Compute support per text budget:

```text
gold-supporting rows per 1,000 snippet characters
contradicting rows per 1,000 snippet characters
support-bearing queries per 1,000 snippet characters
```

### Option C — Keep product-surface framing, but quantify text length

Report average snippet characters per result/provider and explicitly say the study compares **provider surfaces as delivered**, not normalized retrievers.

Best version: do A + C.

## Deliverables

1. Sensitivity table:

   * Brave full surface
   * Brave without extra snippets
   * Tavily
   * Firecrawl
2. Paragraph in Limitations or Results.
3. Updated claim wording if Brave’s advantage shrinks.

## Acceptance criteria

The reviewer should see that you noticed the asymmetry, measured it, and did not hide behind it.

---

# Task 6 — Make the GroundLM fit explicit

**Priority:** Medium-high
**Goal:** Make reviewers immediately see why this belongs in GroundLM.

The paper is currently about search APIs and agents. GroundLM reviewers need to see the link to **grounded generation, faithfulness, retrieval efficiency, and hallucination risk**.

## What to do

Add one framing paragraph to the Introduction and one sentence to the Conclusion.

Suggested intro paragraph:

> For grounded language-model systems, the retrieval API is part of the grounding interface. It determines which evidence is exposed before generation, which contradictions enter context, and how much retrieval budget is spent before an answer is produced. Decision-surface evaluation therefore measures not only retrieval quality, but also the faithfulness and efficiency conditions under which grounded answers are generated.

Suggested conclusion sentence:

> For GroundLM-style systems, grounding should be evaluated not only by final answer correctness, but also by the evidence surface that shapes what the model can faithfully use before it generates.

## Deliverables

1. One new paragraph in Introduction.
2. One explicit GroundLM-aligned sentence in Discussion or Conclusion.
3. Maybe one keyword update:

   * grounded generation
   * RAG evaluation
   * search APIs
   * tool-using agents
   * faithfulness
   * retrieval efficiency

## Acceptance criteria

A reviewer should not need to infer the workshop fit. The paper should tell them directly.

---

# Task 7 — Rename confusing metrics and tighten terminology

**Priority:** Medium
**Goal:** Remove easy reviewer nitpicks.

## Specific changes

Change:

```text
answer-agnostic contradiction-to-gold ratio
```

to:

```text
answer-model-independent contradiction-to-gold ratio
```

or simply:

```text
surface contradiction-to-gold ratio
```

Reason: the metric still depends on the gold answer, so “answer-agnostic” can be misread.

Change:

```text
visible support
```

to one of:

```text
pre-fetch support
trajectory-visible support
page-discovered support
```

depending on what is being measured.

Define:

```text
F1
```

in Table 1. Right now Table 1 includes F1, but the paper should say exactly whether this is token-level F1, normalized answer F1, semantic F1, or something else.

## Deliverables

1. Global terminology pass.
2. Updated Table 1 caption.
3. Updated Appendix A definitions.
4. Search for old phrase “answer-agnostic” and replace.

## Acceptance criteria

A reviewer should not be able to reject on unclear metric definitions.

---

# Task 8 — Add 1–2 qualitative case studies

**Priority:** Medium
**Goal:** Make the paper more memorable and less table-only.

The current paper has a very strong finding: answer text is often present somewhere, yet the agent still answers incorrectly. That is a great story, but it needs examples.

## What to do

Pick two traces from `results/trace_views/`:

### Case Study A — “Answer visible but unused”

The gold answer appears in the snippet or fetched page, but the model gives the wrong final answer.

Explain:

```text
question
provider
where the gold answer appeared
what the agent fetched
what wrong answer it gave
why this shows decision-surface failure
```

### Case Study B — “Contradiction contamination”

A provider surface contains both gold-supporting and contradicting evidence, and the agent follows the wrong evidence.

Explain:

```text
question
provider
gold-supporting row
contradicting row
agent action
final answer
```

## Paper placement

Best location:

```text
End of Section 5
```

or

```text
Short boxed qualitative examples before Discussion
```

## Deliverables

1. Two short examples, 4–6 lines each.
2. Optional appendix with fuller trace excerpts.
3. Do not overquote web content; paraphrase where possible.

## Acceptance criteria

A reviewer should come away understanding the mechanism, not just the metric.

---

# Task 9 — Move key retrieval diagnostics from appendix to main paper

**Priority:** Medium
**Goal:** Strengthen the “accuracy is insufficient” argument.

Appendix J has useful diagnostics like:

```text
gold URL exact hit
gold domain hit
answer in snippet
answer in fetched page
answer in any retrieved text
wrong despite answer text
```

These are too important to hide fully in the appendix.

## What to do

Add a compressed main-text table with only the most important rows:

| Metric                    | Brave | Tavily | Firecrawl |
| ------------------------- | ----: | -----: | --------: |
| Gold URL exact hit        |    59 |     57 |        60 |
| Answer in snippet surface |    71 |     60 |        54 |
| Answer in fetched page    |    52 |     57 |        61 |
| Wrong despite answer text |    57 |     56 |        53 |

Then say:

> Traditional retrieval proxies look strong and similar across providers, but final answer correctness remains low. This motivates decision-surface diagnostics rather than URL-hit metrics alone.

## Deliverables

1. Small main-text diagnostic table.
2. Move full table to appendix.
3. Add one paragraph interpreting the mismatch.

## Acceptance criteria

The reader should clearly see why ordinary retrieval metrics are not enough.

---

# Task 10 — Add run dates, API settings, and reproducibility details in main text

**Priority:** Medium
**Goal:** Protect against reproducibility criticism.

Commercial search APIs change frequently. The paper has request configs in the appendix, but the main protocol should state when the experiment ran and what was frozen.

## What to add

In Section 3, add:

```text
Run date or date range
Provider API endpoints/settings
Region/language settings
Safe search settings
Number of results requested
Whether raw content was disabled
Fetch backend version/config
Cache policy
```

Example sentence:

> All provider calls were run between [date] and [date] with US/en settings, top-10 web results, and provider-side page extraction disabled where configurable. All fetched page text came from the shared Jina Reader backend and was cached before judging.

## Deliverables

1. One paragraph in Experimental Protocol.
2. Appendix D remains the detailed table.
3. Artifact manifest includes run date and config hash if available.

## Acceptance criteria

A reviewer should understand that provider outputs are time-sensitive and that the run is still reproducible from committed traces.

---

# Task 11 — Reframe contribution claims to avoid overclaiming

**Priority:** Medium
**Goal:** Keep the paper confident but not brittle.

## Current risk

The paper could be read as saying:

> Brave is snippet-rich, Tavily is rank-concentrated, Firecrawl is exploration-heavy.

That is okay descriptively, but with 100 questions and one agent, you should avoid implying universal provider traits.

## What to do

Use careful language:

Instead of:

```text
Brave is snippet-rich.
```

say:

```text
In this run, Brave behaves as a snippet-rich surface.
```

Instead of:

```text
Tavily concentrates gold at rank 1.
```

say:

```text
Under our configuration, Tavily shows stronger rank-1 concentration.
```

Instead of:

```text
Firecrawl encourages broad exploration.
```

say:

```text
The fixed agent fetched more often under the Firecrawl surface.
```

## Deliverables

1. Tone pass through Abstract, Results, Discussion, Conclusion.
2. Add “under this configuration” where appropriate.
3. Keep the core claim strong: **accuracy parity hides evidence-economy differences**.

## Acceptance criteria

The paper should sound rigorous, not like a provider leaderboard.

---

# Task 12 — Add a short “what should practitioners do?” paragraph

**Priority:** Medium-low
**Goal:** Make the contribution useful and workshop-friendly.

The paper already has a practitioner-facing idea, but it can be sharper.

## What to add

In Discussion, add a paragraph like:

> A practitioner evaluating search APIs for a grounded agent should not only measure final answer accuracy. They should log pre-fetch support, contradiction exposure, fetch rate, and support captured per fetch. If a provider is snippet-rich, snippet-first policies may be efficient. If support is rank-concentrated, rank-1 or top-3 fetching may be sufficient. If support is sparse, broader exploration or provider routing may be needed.

## Deliverables

1. One paragraph in Discussion.
2. Optional bullet list of metrics practitioners can compute from traces.

## Acceptance criteria

The paper should leave readers with an actionable evaluation recipe.

---

# Suggested execution order

Do them in this order:

1. **Task 1:** split pre-fetch/post-fetch support
2. **Task 7:** terminology cleanup
3. **Task 3:** offline policy ablation
4. **Task 4:** uncertainty estimates
5. **Task 5:** Brave snippet sensitivity
6. **Task 2:** judge validation
7. **Task 6:** GroundLM framing
8. **Task 8:** qualitative case studies
9. **Task 9:** move diagnostics into main paper
10. **Task 10:** run dates/configs
11. **Task 11:** overclaiming pass
12. **Task 12:** practitioner paragraph

The first six are the real approval-odds boosters. The rest improve polish and reviewer confidence.
