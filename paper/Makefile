PAPER = main
FIGURE_TEX = figures/numbers.tex \
	figures/fig_architecture.tikz.tex \
	figures/fig_provider_profiles.tikz.tex \
	figures/fig_partition.tikz.tex

all: $(PAPER).pdf

$(FIGURE_TEX): figures/make_figures.py
	python3 figures/make_figures.py --render-only

$(PAPER).pdf: $(PAPER).tex refs.bib acl.sty acl_natbib.bst $(FIGURE_TEX)
	pdflatex -interaction=nonstopmode $(PAPER).tex
	bibtex $(PAPER)
	pdflatex -interaction=nonstopmode $(PAPER).tex
	pdflatex -interaction=nonstopmode $(PAPER).tex

quick: $(PAPER).tex $(FIGURE_TEX)
	pdflatex -interaction=nonstopmode $(PAPER).tex

audit: figures/make_figures.py
	python3 figures/make_figures.py

clean:
	rm -f *.aux *.log *.out *.bbl *.blg *.toc *.synctex.gz *.fls *.fdb_latexmk

clean-audit:
	rm -f figures/decision_surface_audit.json figures/decision_surface_audit.md

distclean: clean clean-audit
	rm -f $(PAPER).pdf

.PHONY: all quick audit clean clean-audit distclean
