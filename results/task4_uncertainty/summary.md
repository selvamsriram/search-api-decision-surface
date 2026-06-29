# Task 4 paired-bootstrap uncertainty

Bootstrap unit: question ID. Replicates: 10,000. Seed: 20260628. Intervals are percentile 95% CIs.

## Provider metric intervals

| Metric | Brave | Tavily | Firecrawl |
|---|---:|---:|---:|
| Correct /100 | 25 [17, 34] | 25 [17, 34] | 26 [18, 35] |
| Pre-fetch support /100 | 30 [21, 39] | 16 [9, 23] | 16 [9, 23] |
| Rank-1 pre-fetch | 12.9 [7.1, 19.4] | 50.0 [31.2, 78.9] | 13.3 [4.2, 26.3] |
| Surface c:g | 0.92 [0.49, 1.73] | 1.87 [0.83, 4.47] | 2.59 [1.11, 8.00] |
| Fetched queries /100 | 65 [56, 74] | 76 [67, 84] | 81 [73, 89] |
| Avg. fetch calls | 1.02 [0.81, 1.25] | 1.30 [1.06, 1.55] | 1.28 [1.08, 1.50] |
| Tokens/query | 59,627 [47,706, 72,908] | 54,156 [44,304, 64,991] | 57,979 [44,635, 72,878] |

## Paired provider differences

Differences are left minus right in the metric's native units.

| Metric | Brave-Tavily | Brave-Firecrawl | Tavily-Firecrawl |
|---|---:|---:|---:|
| Correct /100 | 0 [-9, 9] | -1 [-10, 8] | -1 [-10, 8] |
| Pre-fetch support /100 | 14 [4, 24] | 14 [6, 22] | 0 [-8, 8] |
| Rank-1 pre-fetch | -37.1 [-67.3, -16.8] | -0.5 [-13.3, 10.1] | 36.7 [18.8, 66.4] |
| Surface c:g | -0.95 [-3.22, 0.00] | -1.68 [-6.78, -0.36] | -0.72 [-4.86, 0.53] |
| Fetched queries /100 | -11 [-19, -3] | -16 [-25, -7] | -5 [-12, 1] |
| Avg. fetch calls | -0.28 [-0.55, -0.02] | -0.26 [-0.51, -0.02] | 0.02 [-0.23, 0.27] |
| Tokens/query | 5,471 [-4,591, 16,176] | 1,648 [-11,834, 13,959] | -3,823 [-18,019, 9,064] |

## Decision-cell correctness intervals

| Provider | SMART | MISSED | BLIND | NOOP |
|---|---:|---:|---:|---:|
| Brave | 3/3 (100% [100, 100]) | 11/27 (41% [22, 60]) | 11/54 (20% [10, 32]) | 0/16 (0% [0, 0]) |
| Tavily | 1/3 (33% [0, 100]) | 7/13 (54% [25, 82]) | 16/63 (25% [15, 37]) | 1/21 (5% [0, 16]) |
| Firecrawl | 1/3 (33% [0, 100]) | 7/13 (54% [25, 82]) | 18/70 (26% [16, 36]) | 0/14 (0% [0, 0]) |

## Interpretation

- Final correctness differences are small: every pairwise correctness interval includes zero.
- Brave's pre-fetch support advantage is larger: Brave-Tavily and Brave-Firecrawl differences are both +14 queries, with intervals that stay positive.
- Rank concentration separates Tavily from the others: Tavily's rank-1 pre-fetch share is much higher, and the paired intervals for Brave-Tavily and Tavily-Firecrawl exclude zero.
- Surface contradiction exposure is directionally higher for Tavily and Firecrawl than Brave, but ratio intervals are wider because the denominator is the number of gold-supporting snippet rows.
