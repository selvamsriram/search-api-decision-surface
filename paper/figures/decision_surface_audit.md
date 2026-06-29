# Decision-surface audit

Source mode: `raw_judge+semantic_tsv`.

Correctness is `semantic_match` from `results/em_vs_semantic_audit.tsv`; exact match and normalized token F1 are retained as deterministic answer-overlap diagnostics.

| Provider | Correct | EM | Gain | Pre-fetch support | Post-fetch discovered | Trajectory-visible | SMART | MISSED | BLIND | NO-OP | c:g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Brave | 25 | 21 | +4 | 30 | 3 | 33 | 3/3 | 27/11 | 54/11 | 16/0 | 0.92 |
| Tavily | 25 | 21 | +4 | 16 | 8 | 24 | 3/1 | 13/7 | 63/16 | 21/1 | 1.87 |
| Firecrawl | 26 | 23 | +3 | 16 | 3 | 19 | 3/1 | 13/7 | 70/18 | 14/0 | 2.59 |

## Semantic EM-miss examples

### Brave
- `Astra Zeneca` vs. `AstraZeneca`: EM-MISS (EM=0 but correct): Spacing only: "Astra Zeneca" == "AstraZeneca"
- `UnionPay` vs. `China UnionPay`: EM-MISS (EM=0 but correct): Same entity: "China UnionPay" is the full name of "UnionPay"
- `US$120,000` vs. `$120,000`: EM-MISS (EM=0 but correct): Same amount: "$120,000" == "US$120,000"
- `313` vs. `313 days`: EM-MISS (EM=0 but correct): Same value: "313 days" == "313"

### Tavily
- `Astra Zeneca` vs. `AstraZeneca`: EM-MISS (EM=0 but correct): Spacing only: "Astra Zeneca" == "AstraZeneca"
- `US$120,000` vs. `$120,000`: EM-MISS (EM=0 but correct): Same amount: "$120,000" == "US$120,000"
- `3 players` vs. `3`: EM-MISS (EM=0 but correct): Same value: "3" == gold "3 players"
- `16 years` vs. `16 years old`: EM-MISS (EM=0 but correct): Same value: "16 years old" == "16 years"

### Firecrawl
- `Astra Zeneca` vs. `AstraZeneca`: EM-MISS (EM=0 but correct): Spacing only: "Astra Zeneca" == "AstraZeneca"
- `Bohemian Rhapsody` vs. `Bohemian Rhapsody, 9,948,386 viewers`: EM-MISS (EM=0 but correct): Correct entity + extra detail: "Bohemian Rhapsody, 9,948,386 viewers"
- `16 years` vs. `16 years old`: EM-MISS (EM=0 but correct): Same value: "16 years old" == "16 years"
