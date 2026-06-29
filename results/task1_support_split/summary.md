# Task 1 support split numbers

These numbers are computed from existing Kimi judge JSONLs and `results/em_vs_semantic_audit.tsv`.

## Support counts

| Provider | Pre-fetch support | Post-fetch discovered | Trajectory-visible | No pre-fetch support | Legacy visible support |
|---|---:|---:|---:|---:|---:|
| Brave | 30 | 3 | 33 | 70 | 33 |
| Tavily | 16 | 8 | 24 | 84 | 24 |
| Firecrawl | 16 | 3 | 19 | 84 | 19 |

## Decision partition using pre-fetch support

Each cell is `queries / semantic-correct answers (rate)`.

| Provider | SMART | MISSED | BLIND | NO-OP |
|---|---:|---:|---:|---:|
| Brave | 3 / 3 (100%) | 27 / 11 (41%) | 54 / 11 (20%) | 16 / 0 (0%) |
| Tavily | 3 / 1 (33%) | 13 / 7 (54%) | 63 / 16 (25%) | 21 / 1 (5%) |
| Firecrawl | 3 / 1 (33%) | 13 / 7 (54%) | 70 / 18 (26%) | 14 / 0 (0%) |

## Valid row counts

| Provider | Snippet-only rows | Page-visible rows | Pre-fetch support rows | Page-visible pre-fetch rows | Page extracted-gold rows | Post-fetch discovered rows |
|---|---:|---:|---:|---:|---:|---:|
| Brave | 2095 | 101 | 101 | 4 | 6 | 3 |
| Tavily | 2339 | 125 | 34 | 3 | 9 | 9 |
| Firecrawl | 2085 | 124 | 30 | 3 | 5 | 3 |
