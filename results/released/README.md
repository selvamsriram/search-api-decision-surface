# Released derived results

These files contain numeric measurements, query identifiers, and audit labels.
They omit URLs returned by the providers, document titles, search strings,
snippets, fetched text, free-text audit notes, and judge requests/responses.

- `answer_audit.csv`: exact-match and semantic-correctness labels for 300 provider/query pairs.
- `query_actions.csv`: final action cells, fetch counts, and evidence-label counts for the same pairs. `after_cell` is the corrected paper cell.
- `decision_partition.csv`: query and correct-answer counts by provider/cell.
- `query_diagnostics.csv`: first-search support/rank/reciprocal-rank measurements and trajectory contradiction counts/bounds. Empty support ranks indicate no observed supporting result.
- `label_audit.csv`: 180 human decisions; unclear values remain in the data and are excluded only from the agreement denominator.
- `provider_metrics.csv`, `paired_differences.csv`: first-search/contradiction point estimates, paired-question intervals, and missing-label bounds.
- `common_first_query_*.csv`: the 74-question common-first-query sensitivity.
- `first_support_rank_distribution.csv`: query-level first-support ranks.
- `deduplicated_*.csv`: independent-observation contradiction ratios and paired intervals.
- `*_cis.csv`: the paper's bootstrap and decision-cell intervals.
- `hashes.json`: SHA-256 values for these CSVs.

The CSVs support checking aggregate calculations from the reported labels and
measurements. They do not permit independent re-annotation of the withheld
evidence surfaces. Full methods, denominators, and scope are in the paper.
`scripts/export_release_metrics.py` derives these files from the authors' local
records through explicit column allowlists; it makes no API calls. Its inputs
are not part of this release. The camera-ready PDF build uses frozen figures
and does not require those inputs.
