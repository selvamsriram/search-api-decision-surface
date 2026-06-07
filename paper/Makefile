PAPER_SUBMISSION = main_submission
PAPER_PREPRINT = main_preprint
FIGURE_SCRIPT = figures/make_figures.py

all: submission preprint

# Strict, audited figure/macro regeneration. This reads results/em_vs_semantic_audit.tsv
# and raw LFS judge JSONLs; run `git lfs pull` before this target.
figures:
	python3 $(FIGURE_SCRIPT)

submission: figures $(PAPER_SUBMISSION).tex paper_shared.tex preamble.tex refs.bib
	pdflatex -interaction=nonstopmode $(PAPER_SUBMISSION).tex
	bibtex $(PAPER_SUBMISSION)
	pdflatex -interaction=nonstopmode $(PAPER_SUBMISSION).tex
	pdflatex -interaction=nonstopmode $(PAPER_SUBMISSION).tex

preprint: figures $(PAPER_PREPRINT).tex paper_shared.tex preamble.tex refs.bib
	pdflatex -interaction=nonstopmode $(PAPER_PREPRINT).tex
	bibtex $(PAPER_PREPRINT)
	pdflatex -interaction=nonstopmode $(PAPER_PREPRINT).tex
	pdflatex -interaction=nonstopmode $(PAPER_PREPRINT).tex

# Layout-only target. Uses semantic TSV if present and last validated bucket constants
# if raw LFS judge files are unavailable. Do not use this for final numbers.
render-only:
	python3 $(FIGURE_SCRIPT) --render-only

quick: render-only
	pdflatex -interaction=nonstopmode $(PAPER_SUBMISSION).tex

clean:
	rm -f *.aux *.bbl *.blg *.log *.out *.toc *.fls *.fdb_latexmk *.synctex.gz
	rm -f figures/*.dot figures/*.svg

distclean: clean
	rm -f $(PAPER_SUBMISSION).pdf $(PAPER_PREPRINT).pdf

.PHONY: all figures submission preprint render-only quick clean distclean
