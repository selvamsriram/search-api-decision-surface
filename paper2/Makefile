FIGSCRIPT = figures/make_figures.py

all: submission preprint

figures:
	python3 $(FIGSCRIPT) --render-only

audit:
	python3 $(FIGSCRIPT) --audit

submission: figures main_submission.pdf
preprint: figures main_preprint.pdf
quick: figures
	pdflatex -interaction=nonstopmode main_submission.tex
	pdflatex -interaction=nonstopmode main_preprint.tex

main_submission.pdf: main_submission.tex paper_shared.tex preamble.tex refs.bib figures/numbers.tex figures/*.pdf
	pdflatex -interaction=nonstopmode main_submission.tex
	@if command -v bibtex >/dev/null 2>&1; then bibtex main_submission; else echo "bibtex not found; using checked-in main_submission.bbl"; fi
	pdflatex -interaction=nonstopmode main_submission.tex
	pdflatex -interaction=nonstopmode main_submission.tex

main_preprint.pdf: main_preprint.tex paper_shared.tex preamble.tex refs.bib figures/numbers.tex figures/*.pdf
	pdflatex -interaction=nonstopmode main_preprint.tex
	@if command -v bibtex >/dev/null 2>&1; then bibtex main_preprint; else echo "bibtex not found; using checked-in main_preprint.bbl"; fi
	pdflatex -interaction=nonstopmode main_preprint.tex
	pdflatex -interaction=nonstopmode main_preprint.tex

clean:
	rm -f *.aux *.log *.out *.blg *.toc *.fls *.fdb_latexmk *.synctex.gz

clean-bbl:
	rm -f *.bbl

distclean: clean
	rm -f main_submission.pdf main_preprint.pdf main.pdf

.PHONY: all submission preprint quick figures audit clean clean-bbl distclean
