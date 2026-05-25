PAPER = main

all: $(PAPER).pdf

$(PAPER).pdf: $(PAPER).tex refs.bib acl.sty acl_natbib.bst
	pdflatex -interaction=nonstopmode $(PAPER).tex
	bibtex $(PAPER)
	pdflatex -interaction=nonstopmode $(PAPER).tex
	pdflatex -interaction=nonstopmode $(PAPER).tex

quick: $(PAPER).tex
	pdflatex -interaction=nonstopmode $(PAPER).tex

clean:
	rm -f *.aux *.log *.out *.bbl *.blg *.toc *.synctex.gz *.fls *.fdb_latexmk

distclean: clean
	rm -f $(PAPER).pdf

.PHONY: all quick clean distclean
