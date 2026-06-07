# Decision-surface audit

Source mode: `raw_judge+semantic_tsv`.

Correctness is `semantic_match` from `results/em_vs_semantic_audit.tsv`; exact match is retained as an audit column.

| Provider | Correct | EM | Gain | Visible support | SMART | MISSED | BLIND | NO-OP | c:g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Brave | 25 | 21 | +4 | 33 | 8/4 | 25/11 | 51/10 | 0/0 | 0.92 |
| Tavily | 25 | 21 | +4 | 24 | 11/7 | 13/7 | 55/10 | 0/0 | 1.87 |
| Firecrawl | 26 | 23 | +3 | 19 | 7/2 | 12/6 | 67/18 | 0/0 | 2.59 |

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
