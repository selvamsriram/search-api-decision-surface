# Phase 1 100-Query Dataset Selection Rationale

This file records the deterministic V1 sampling methodology for selecting 100 queries from SealQA Hard.

## Source

- Dataset: `vtllms/sealqa`
- Subset/config: `seal_hard`
- Source rows: `254`
- Selected rows: `100`
- Random seed: `20260509`

## Method

1. Load all SealQA Hard rows from `data/raw/seal-hard.jsonl`.
2. Assign stable query IDs from a SHA-256 hash of each question.
3. Build a cross-table over `freshness x search_results x topic`.
4. Allocate 100 slots proportionally with largest-remainder rounding, capped by cell availability.
5. Randomly sample within each cell using the fixed seed.
6. Verify coverage for `question_types` and `effective_year`; diagnostics below capture drift from the source distribution.

## Distribution Diagnostics

### freshness

| Category | Source % | Sample % | Source n | Sample n |
| --- | ---: | ---: | ---: | ---: |
| fast-changing | 25.20 | 25.00 | 64 | 25 |
| never-changing | 31.10 | 32.00 | 79 | 32 |
| slow-changing | 43.70 | 43.00 | 111 | 43 |

Max absolute percentage-point delta: `0.9`

### search_results

| Category | Source % | Sample % | Source n | Sample n |
| --- | ---: | ---: | ---: | ---: |
| conflicting | 56.69 | 57.00 | 144 | 57 |
| unhelpful | 43.31 | 43.00 | 110 | 43 |

Max absolute percentage-point delta: `0.31`

### topic

| Category | Source % | Sample % | Source n | Sample n |
| --- | ---: | ---: | ---: | ---: |
| Entertainment | 21.65 | 22.00 | 55 | 22 |
| History & Geography | 8.27 | 8.00 | 21 | 8 |
| Others | 12.20 | 12.00 | 31 | 12 |
| Politics | 9.06 | 9.00 | 23 | 9 |
| Science & Technology | 26.77 | 27.00 | 68 | 27 |
| Sports | 22.05 | 22.00 | 56 | 22 |

Max absolute percentage-point delta: `0.35`

### effective_year

| Category | Source % | Sample % | Source n | Sample n |
| --- | ---: | ---: | ---: | ---: |
| 2024 | 19.29 | 16.00 | 49 | 16 |
| 2025 | 22.05 | 23.00 | 56 | 23 |
| before 2024 | 58.66 | 61.00 | 149 | 61 |

Max absolute percentage-point delta: `3.29`

### question_types

| Category | Source % | Sample % | Source n | Sample n |
| --- | ---: | ---: | ---: | ---: |
| advanced reasoning | 72.44 | 72.00 | 184 | 72 |
| cross-lingual reasoning | 5.51 | 5.00 | 14 | 5 |
| entity/event disambiguation | 58.27 | 61.00 | 148 | 61 |
| false-premise | 4.33 | 2.00 | 11 | 2 |
| temporal tracking | 13.78 | 13.00 | 35 | 13 |

Max absolute percentage-point delta: `2.73`

## Notes

- The selected query records live in `data/queries/phase1_100.json`.
- Gold answers and gold URLs are retained for offline grading and metrics; the agent runner does not expose them to the model.
- The raw source file is pinned locally so this V1 selection can be reproduced before pushing the sample to Hugging Face.
