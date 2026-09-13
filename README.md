# Similar Accuracy, Unequal Evidence

**Search APIs as Decision Surfaces for Tool-Using Agents**

Sriram Selvam and Anneswa Ghosh, Independent Researchers

This repository accompanies a diagnostic study of Brave, Tavily, and Firecrawl
on a deterministic 100-question subset of SealQA-Hard using a fixed GPT-5.4
agent harness. Results describe that configuration; other models or changes to
orchestration may yield better performance.

## Paper and released artifacts

- [Camera-ready paper](output/pdf/camera-ready.pdf): eight main pages, 17 pages including statements, references, and appendices.
- [Standalone LaTeX package](output/camera-ready-source.zip).
- [Derived results](results/released/README.md): numeric measurements and audit labels, without copied evidence text.
- `config/`, `src/`, `scripts/`: experiment configuration, agent and judge prompts, schemas, sampling, evaluation, bootstrap analysis, and figure-generation code.
- [Benchmark data and license](data/README.md): source rows and the deterministic sample.
- [Project page](site/README.md): a static site built from the paper's frozen numbers.

To respect provider policies and third-party content rights, we do not
redistribute complete execution traces, raw provider responses, search snippets,
or fetched page text. Copies of that content in judge inputs, audit records,
and rendered trajectories are also excluded. The released labels and numeric
measurements support aggregate checks; they do not replace the withheld evidence.
Git LFS is not required for this release.

## Install and check

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
python3 scripts/check_public_release.py
```

The tests and release checks run offline and need no API keys. Python 3.11 or
newer is required. `release/public-files.txt` is the explicit publication
allowlist; review it when adding public files.

## Build the paper

With a TeX installation including `latexmk` on PATH:

```bash
make -C paper
```

The default build uses frozen, audited figures and numbers and needs no private
records or API credentials. It writes the clean PDF, standalone source ZIP,
and build manifest to `output/`. See [paper build notes](paper/README.md).

## Rerun the protocol

Copy `.env.example` to the ignored `.env` and supply your own Azure OpenAI,
search-provider, and fetch-backend credentials. Shell variables take precedence.
Live runs use paid services and require the applicable permissions.

```bash
python3 scripts/run_phase1.py --provider brave --fetch-tool --page-fetch-backend jina --limit 1 --output data/traces/brave-local.jsonl
```

Repeat with `--provider tavily` or `--provider firecrawl`. Remove `--limit 1`
for a full sampled run. Outputs under `data/traces/`, `data/page_cache/`, and
non-release `results/` paths are local and ignored by Git.

The analysis CLIs accept locally generated records:

- `build_provider_comparison.py`, `evaluate_traces.py`: outcome and trace metrics.
- `run_llm_judge.py`: judge requests; live calls require `--execute` and Kimi credentials.
- `camera_ready_gate2_audit.py`: fetch-action and deduplication audits.
- `camera_ready_gate3_diagnostics.py`: first-search diagnostics and paired intervals.
- `task4_bootstrap_uncertainty.py`: paired-question bootstrap analysis.
- `render_trace.py`, `trace_dashboard.py`: local trajectory inspection.

Use `python3 scripts/<name>.py --help` for each interface. Historical analysis
defaults refer to the authors' local filenames, which are not distributed.
`export_release_metrics.py` exports approved columns from those local records;
it is not needed to build the paper. Live search is time-varying, so reruns
reproduce the procedure and may return different evidence and outcomes.
