# Camera-ready paper

**Similar Accuracy, Unequal Evidence: Search APIs as Decision Surfaces for Tool-Using Agents**

`main_camera_ready.tex` is the author-visible ACL final wrapper. Build from the
repository root with a TeX installation and `latexmk` on PATH:

```bash
make -C paper
```

The default target builds from the frozen figures and `figures/numbers.tex`.
It does not regenerate measurements or require private traces, judge records,
Git LFS, or API credentials. The main paper is eight pages; statements,
references, and appendices bring the total to 17 pages.

Outputs are `output/pdf/camera-ready.pdf`, `output/camera-ready-source.zip`,
and `output/build-manifest.json`. The ZIP includes `main.bbl`; extract it and
run `latexmk -pdf main.tex` to build independently. Temporary build files live
in the ignored `paper/build/camera-ready/` directory.

## Optional regeneration using local research records

`make -C paper figures` explicitly reruns the figure and macro generator.
This requires locally held trace, judge, and answer-audit records. Those inputs
are withheld from the public release. Do not use this target merely to compile
the PDF. The figure source and exported images are included for inspection.

Figure 3's PNG renderer additionally needs Node.js, Playwright, and Chromium.
`NODE_BINARY`, `PLAYWRIGHT_MODULE`, and `CHROMIUM_EXECUTABLE` can select local
installations. Fonts are embedded in the designer HTML and rendering blocks
network requests. The published figures are already exported.

The ACL style and bibliography files are included. The final build retains
the Section 4 judge-schema table in the main paper. Original submitted PDFs
and highlighted revision comparisons are author-local review records.

The designer HTML embeds IBM Plex Sans and Mono fonts. Their upstream copyright
notice and SIL Open Font License are included in `figures/LICENSE-IBM-Plex.txt`
([IBM Plex source](https://github.com/IBM/plex/blob/master/LICENSE.txt)).
