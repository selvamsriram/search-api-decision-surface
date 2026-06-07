# ACL paper package: Beyond Answer Accuracy: Search APIs as Decision Surfaces for Tool-Using Agents

This directory contains the ACL review and preprint sources for the paper.

## Entry points

- `main_submission.tex` — anonymous ACL review build.
- `main.tex` — alias for `main_submission.tex`.
- `main_preprint.tex` — author-visible preprint build.

## Build

From the repository root, make sure large trace and judge files are present before producing a final paper:

```bash
git lfs pull
cd paper
make submission
make preprint
```

The default build is strict: `figures/make_figures.py` refuses to use Git LFS pointer files for judge JSONLs because decision-cell correctness is computed from `semantic_match` joined with the per-URL judge rows. The render-only target is for layout drafting only:

```bash
make render-only
make quick
```

## arXiv package

Use the author-visible preprint build for arXiv. Do not upload this whole
directory, because `main.tex` is the anonymous ACL wrapper and the directory
also contains auxiliary files. Instead run:

```bash
cd paper
make preprint
make arxiv
```

This writes a clean source archive to:

```text
paper/build/search-api-decision-surface-arxiv.tar.gz
```

The archive stages `main_preprint.tex` as `main.tex`, copies
`main_preprint.bbl` as `main.bbl`, includes only the TeX sources, ACL style,
bibliography files, generated paper macros, and the four figures actually used
by the manuscript, then recompiles the staged package before creating the
tarball.

## Layout notes

The main paper stays in ACL two-column layout. The appendix switches to one-column after the bibliography to avoid narrow-column overlap for audit definitions and diagnostic tables. Figures are deterministic Graphviz DOT renderings with committed PDF/SVG outputs.

## Generated files

`figures/make_figures.py` writes:

- `figures/numbers.tex`
- `figures/fig1_architecture.{dot,pdf,svg}`
- `figures/fig2_provider_profiles.{dot,pdf,svg}`
- `figures/fig3_decision_partition.{dot,pdf,svg}`
- `figures/fig4_complementarity.{dot,pdf,svg}`
- `figures/decision_surface_audit.{json,md}`
