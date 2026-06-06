# ACL paper package: Search APIs as decision surfaces

This directory is a drop-in replacement/overlay for `paper/` in the repository. It contains both the anonymous submission source and the preprint source.

## Entry points

- `main_submission.tex` - ACL review / anonymous submission wrapper.
- `main_preprint.tex` - ACL preprint wrapper with author block.
- `main.tex` - copy of the submission wrapper for systems that expect `main.tex`.
- `paper_shared.tex` - all paper content shared by both versions.
- `preamble.tex` - packages/macros.
- `refs.bib` - bibliography source.
- `main_submission.bbl`, `main_preprint.bbl`, `main.bbl` - checked-in fallback bibliography files for environments without `bibtex`.

The package assumes the repository already contains official ACL style files (`acl.sty`, `acl_natbib.bst`). The original repo had them in `paper/`; this overlay does not replace those official style files.

## Build

```bash
cd paper
make submission    # anonymous ACL review PDF
make preprint      # non-anonymous preprint PDF
make all           # both
```

If `bibtex` is unavailable, the Makefile uses the checked-in `.bbl` files. If `bibtex` is available, it regenerates bibliographies from `refs.bib`.

## Figures and audit

All figures are deterministic Graphviz vector diagrams. Source DOT and rendered PDF/SVG files are in `figures/`.

```bash
python3 figures/make_figures.py --render-only
```

`--render-only` uses last validated constants and never calls an LLM or a search provider.

To recompute the paper numbers from raw artifacts:

```bash
git lfs pull
cd paper
python3 figures/make_figures.py --audit
```

Audit mode consumes the three trace JSONLs, the three judge JSONLs, `provider_per_query.jsonl`, and `provider_summary.json`. It refuses to run if a raw JSONL is still a Git LFS pointer.

## What changed from the earlier draft

- Stronger framing: the paper is now organized around decision surfaces, not provider leaderboards.
- Larger figures: all main figures are Graphviz vector PDFs and designed for full-width ACL placement.
- Stronger related work: RAG, IR, browser agents, tool use, hard-search benchmarks, attribution, and LLM judges.
- Richer appendix: formal metric definitions, dataset distribution, provider requests, judge schema, Wilson intervals, pairwise complementarity, token/fetch diagnostics, and audit manifest.
- Safer claims: visible support is consistently described as a lower bound; decision-cell gaps are descriptive rather than causal.
