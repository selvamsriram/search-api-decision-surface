# Paper Modification: Exact-Match vs. Semantic-Match Audit

**Status:** Proposed modification for `paper/main.tex`
**Date:** 2026-06-04
**Author of audit:** (research-assistant handoff)
**Scope:** Adds a grader-validity audit. Does **not** change any headline conclusion;
it bounds the bias of the Exact-Match (EM) grader the paper relies on.

---

## 1. Motivation

Every accuracy number in the paper is **Exact Match (EM)** as computed by
`src/searchapi_eval/evaluation/grader.py::exact_match`. EM normalizes by:
lower-casing, stripping articles (`a/an/the`), removing punctuation, and mapping
number-words `zero…twenty` to digits. Two strings match iff their normalized forms
are identical.

This is a strict surface grader. The concern: it can mark a **semantically correct**
answer as wrong (false negative) when the surface form differs from the gold string
(e.g. `"$120,000"` vs gold `"US$120,000"`). If those false negatives are unevenly
distributed across providers, they could distort the cross-provider comparison that
is the paper's entire contribution.

We therefore manually re-judged all 300 trajectories (100 queries × 3 providers) for
**semantic** correctness and compared against EM.

---

## 2. Method

1. Extracted `question`, `gold_answer`, `final_answer`, `provider_id`, `query_id`
   from the three main trace files (one row per query per provider, deduped).
2. Recomputed EM per row using the project's own grader
   (`exact_match(final_answer, gold_answer)`). This reproduced the paper's headline
   exactly: **Brave 21 / Tavily 21 / Firecrawl 23** — confirming the extraction is faithful.
3. For every row, a human judge assigned `semantic_match ∈ {match, no_match}`:
   *does the model answer convey the same correct fact as the gold answer, ignoring
   surface formatting?*
4. Tallied EM vs semantic match, per provider and overall, and categorized every
   disagreement.

**Judging rubric (as applied):**
- **Match** = same entity/value, differing only in formatting, currency symbol,
  trailing unit noun, full-vs-short proper name, or an appended correct detail.
- **No-match** = different value/entity, wrong precision (`22%` vs `21.8`), hedged
  ties, or over-inclusive lists that add items not in gold.
- Single judge (the same limitation already disclosed for the Kimi judge). Borderline
  calls were resolved **conservatively** (toward no-match) and are flagged in the data.

---

## 3. Results

### 3.1 Headline table (proposed addition)

| Provider | EM | Semantic match | EM-miss (EM=0, judged correct) | EM acc. | Semantic acc. | Rel. uplift |
|---|---:|---:|---:|---:|---:|---:|
| Brave     | 21 | 25 | 4 | 21% | 25% | +19% |
| Tavily    | 21 | 25 | 4 | 21% | 25% | +19% |
| Firecrawl | 23 | 26 | 3 | 23% | 26% | +13% |
| **Total** | **65** | **76** | **11** | 21.7% | 25.3% | **+17%** |

### 3.2 Key facts

- **EM undercounts correct answers by ~17%** (11 of 65 EM-correct equivalents missed).
- **Zero false positives.** All 65 EM=1 rows were manually verified as truly correct.
  EM is therefore **conservative, never generous** — it only errs by rejecting right
  answers, never by accepting wrong ones.
- **The correction is near-uniform across providers** (+4 / +4 / +3). The cross-provider
  ranking and the "statistically indistinguishable EM" conclusion are **unchanged**.
  This is evidence *for* the robustness of the paper's main claim, not against it.

### 3.3 The 11 EM-miss rows, by failure mode

| Failure mode | n | Examples (gold → model) |
|---|---:|---|
| Trailing unit noun | 4 | `313` → "313 days"; `16 years` → "16 years old" (×2); `3 players` → "3" |
| Whitespace in proper name | 3 | `Astra Zeneca` → "AstraZeneca" (all 3 providers) |
| Currency prefix | 2 | `US$120,000` → "$120,000" (×2) |
| Org full vs short name | 1 | `UnionPay` → "China UnionPay" |
| Correct entity + extra detail | 1 | `Bohemian Rhapsody` → "Bohemian Rhapsody, 9,948,386 viewers" |

Note the largest single source (`Astra Zeneca`, a stray space **in the gold label**)
penalizes all three providers identically — it is a dataset-labeling artifact, not a
model difference.

### 3.4 Borderline rows (judged no-match, but debatable)

Flagged in `judgement_note` so they can be re-decided. All kept as **no-match** here:

| query_id | gold → model | Providers | Rationale for no-match |
|---|---|---|---|
| `sealhard_b01f894cc6d2` | `Western Punjabi` → "Punjabi" | all 3 | Gold means Lahnda (ISO) specifically; "Punjabi" usually denotes the 2nd-largest |
| `sealhard_c02ac99c3053` | `celery` → "celery, mustard / lupin / …" | all 3 | Over-inclusive; adds allergens not in gold |
| `sealhard_d6f7180757d7` | `China` → "China and Italy (tied)" | tavily, firecrawl | Hedged tie; gold asserts a single answer |
| `sealhard_4981ad02a6fc` | `US$120,000` → "$120,000 to $150,000" | firecrawl | Hedged range, not a point match |
| `sealhard_c71d4bbb72a2` | `21.8` → "22%" | brave | Rounded; different precision |

**Sensitivity:** if the 3 `Western Punjabi` rows are flipped to match, totals become
**Brave 26 / Tavily 26 / Firecrawl 27** — still indistinguishable across providers.

---

## 4. Recommended changes to `main.tex`

1. **§3 (Headline) or §10 (Limitations):** add one paragraph stating EM is a strict
   lower bound that undercounts correctness by ~17% (11/65), with **0 false positives**,
   and that the correction is provider-uniform so all conclusions hold. Suggested text:

   > *Exact match is a strict surface grader and undercounts semantically correct
   > answers. A manual re-judgment of all 300 trajectories finds 11 EM false negatives
   > (formatting-only mismatches such as `US$120,000` vs `$120,000` or `16 years` vs
   > `16 years old`) and zero false positives, lifting accuracy to 25/25/26. Because the
   > correction is near-uniform across providers, the indistinguishable-EM result and
   > all downstream findings are unaffected; the absolute EM figures should be read as a
   > ~17%-conservative lower bound.*

2. **Limitations (§10):** extend the existing "single judge" caveat to note the
   semantic re-judgment is also single-judge and borderline cases were resolved
   conservatively.

3. **Optional new appendix table:** the §3.1 table above.

4. **Optional, stronger fix for any future run:** report an **LLM answer-equivalence
   grader alongside EM** (not replacing it) — EM as the strict floor, semantic match as
   the realistic ceiling. The judge infrastructure already exists
   (`scripts/run_llm_judge.py`); this would make the §3 numbers reproducible rather than
   resting on a manual pass.

> **Caution for whoever edits the partition tables:** the five-cell partition
> (`tab_partition.tex`) and all per-cell EM counts are computed from EM, not semantic
> match. If you switch any *table* to semantic match you must regenerate it from the data
> — do **not** hand-edit. See §5 for how. The cleanest paper edit is to keep EM as the
> primary metric everywhere and add the audit as a bounding caveat.

---

## 5. Sources and data (everything needed to reproduce or verify)

### Primary deliverable (this audit)
- **`results/em_vs_semantic_audit.tsv`** — 300 rows, columns:
  `query_id · provider · question · gold_answer · model_answer · em · semantic_match · judgement · judgement_note`.
  The `judgement_note` column documents every EM-miss reason and every borderline call.
- `results/em_audit_base.tsv` — intermediate extraction (EM only, no judgement),
  useful for re-running the judgement from scratch.

### The grader under audit
- **`src/searchapi_eval/evaluation/grader.py`** — `normalize_answer`, `exact_match`,
  `token_f1`. The `NUMBER_WORDS` map (zero…twenty) is why `"six"` already equals `"6"`
  but `"313 days"` does **not** equal `"313"`.

### Source trajectories (gold + model answers came from here)
- `data/traces/phase1_v1_brave_gpt54_fetch_tool_jina_100.jsonl` (100 rows)
- `data/traces/phase1_v1_tavily_gpt54_fetch_tool_jina_100.jsonl` (101 rows; deduped to 100)
- `data/traces/phase1_v1_firecrawl_gpt54_fetch_tool_jina_100.jsonl` (100 rows)
- Per-record fields used: `question`, `gold_answer`, `final_answer`, `provider_id`, `query_id`.
- Trace schema reference: `data/trace-schema-v1.md`.

### Paper numbers this cross-checks against
- `paper/figures/tables/numbers.tex` — macros `\emBr=21`, `\emTa=21`, `\emFc=23`
  (matched exactly by our recomputation, confirming the extraction).
- `paper/figures/snippet_gold_breakdown.json` / `.md` — the per-query EM audit the
  partition tables are built from.

### How to regenerate the base TSV
```bash
cd /Users/sriramselvam/Code/searchapi-hard-eval
python3 - <<'PY'
import json, csv, sys
sys.path.insert(0,'src')
from searchapi_eval.evaluation.grader import exact_match
files={'brave':'data/traces/phase1_v1_brave_gpt54_fetch_tool_jina_100.jsonl',
       'tavily':'data/traces/phase1_v1_tavily_gpt54_fetch_tool_jina_100.jsonl',
       'firecrawl':'data/traces/phase1_v1_firecrawl_gpt54_fetch_tool_jina_100.jsonl'}
rows=[]
for prov,path in files.items():
    seen=set()
    for line in open(path):
        if not line.strip(): continue
        r=json.loads(line); q=r['query_id']
        if q in seen: continue
        seen.add(q)
        rows.append([q,prov,r['question'],r['gold_answer'],r['final_answer'],
                     int(exact_match(r['final_answer'],r['gold_answer']))])
print(sum(x[5] for x in rows), 'EM-correct of', len(rows))
PY
```
The semantic-match overrides (the 11 EM-miss rows + borderline notes) are the human
judgement layer applied on top; the exact mapping is encoded in
`results/em_vs_semantic_audit.tsv` (`judgement_note` column).

---

## 6. One-line summary for the paper's authors

> EM is a strict, conservative grader: it undercounts correctness by ~17% (11/65, all
> formatting-only false negatives; zero false positives), but the undercount is uniform
> across Brave/Tavily/Firecrawl, so every cross-provider conclusion in the paper stands.
> Report semantic accuracy (25/25/26) as the realistic ceiling and EM (21/21/23) as the
> floor.
