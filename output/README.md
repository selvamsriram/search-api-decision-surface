# Camera-ready delivery

- `pdf/camera-ready.pdf`: clean ACL final-mode paper, eight main pages and 17 total pages.
- `camera-ready-source.zip`: standalone LaTeX sources, bibliography, style, and frozen figures. Extract and run `latexmk -pdf main.tex`.
- `build-manifest.json`: source, PDF, and source-package hashes.
- `verification.json`: completed local checks for these artifacts.

Rebuild with `make -C paper`. The packaging target uses frozen figures and
measurements and needs no private records or API credentials. Original
submissions, highlighted comparisons, and detailed editorial records remain
author-local and are excluded from the release. This package does not itself
confirm an external submission or deployment.
