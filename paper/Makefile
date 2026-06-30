PAPER_SUBMISSION = main_submission
PAPER_PREPRINT = main_preprint
FIGURE_SCRIPT = figures/make_figures.py
ARXIV_BUILD_DIR = build/arxiv
ARXIV_TARBALL = build/search-api-decision-surface-arxiv.tar.gz

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
	pdflatex -interaction=nonstopmode $(PAPER_SUBMISSION).tex

preprint: figures $(PAPER_PREPRINT).tex paper_shared.tex preamble.tex refs.bib
	pdflatex -interaction=nonstopmode $(PAPER_PREPRINT).tex
	bibtex $(PAPER_PREPRINT)
	pdflatex -interaction=nonstopmode $(PAPER_PREPRINT).tex
	pdflatex -interaction=nonstopmode $(PAPER_PREPRINT).tex

arxiv: $(PAPER_PREPRINT).tex $(PAPER_PREPRINT).bbl paper_shared.tex appendix_shared.tex preamble.tex acl.sty acl_natbib.bst refs.bib figures/numbers.tex figures/fig1_pipeline.png figures/fig2_provider_profiles.png figures/fig3_decision_partition.png figures/fig4_complementarity.png
	rm -rf $(ARXIV_BUILD_DIR)
	mkdir -p $(ARXIV_BUILD_DIR)/figures build
	cp $(PAPER_PREPRINT).tex $(ARXIV_BUILD_DIR)/main.tex
	cp $(PAPER_PREPRINT).bbl $(ARXIV_BUILD_DIR)/main.bbl
	cp paper_shared.tex appendix_shared.tex preamble.tex acl.sty acl_natbib.bst refs.bib $(ARXIV_BUILD_DIR)/
	cp figures/numbers.tex figures/fig1_pipeline.png figures/fig2_provider_profiles.png figures/fig3_decision_partition.png figures/fig4_complementarity.png $(ARXIV_BUILD_DIR)/figures/
	cd $(ARXIV_BUILD_DIR) && pdflatex -interaction=nonstopmode main.tex
	cd $(ARXIV_BUILD_DIR) && pdflatex -interaction=nonstopmode main.tex
	cd $(ARXIV_BUILD_DIR) && pdflatex -interaction=nonstopmode main.tex
	tar -C $(ARXIV_BUILD_DIR) -czf $(abspath $(ARXIV_TARBALL)) main.tex main.bbl paper_shared.tex appendix_shared.tex preamble.tex acl.sty acl_natbib.bst refs.bib figures/numbers.tex figures/fig1_pipeline.png figures/fig2_provider_profiles.png figures/fig3_decision_partition.png figures/fig4_complementarity.png

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
	rm -rf build

.PHONY: all figures submission preprint arxiv render-only quick clean distclean
