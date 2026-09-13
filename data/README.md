# Benchmark inputs

`raw/seal-hard.jsonl` is the 254-row SealQA-Hard snapshot used for the study;
`queries/phase1_100.json` is the derived 100-question sample. These contain
benchmark questions, answers, reference URLs, and dataset metadata, not the
responses collected from Brave, Tavily, Firecrawl, or Jina. The optional `golds`
lists in this stored sample are empty. `100-dataset-selection-rationale.md`
describes the deterministic selection and `trace-schema-v1.md` documents run
records without including actual trajectories.

Source: [vtllms/sealqa](https://huggingface.co/datasets/vtllms/sealqa).
The upstream dataset is distributed under Apache License 2.0; its license is
included in `LICENSE-SealQA`. The JSON representation and stratified selection
are derived artifacts. The paper cites the SealQA authors. This notice applies
to the benchmark data, not to commercial API responses or linked webpages.

`traces/` and `page_cache/` are local output directories excluded from Git and
the public release. Live reruns require the researcher's own credentials and
applicable permissions, and may return different evidence.
