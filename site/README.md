# Research project page

The project page for **Similar Accuracy, Unequal Evidence: Search APIs as Decision
Surfaces for Tool-Using Agents**, accepted at GroundLM.

This is a static site with no frontend dependencies, external fonts, analytics,
or runtime services. The Python standard library builds its publishable files.

## Preview locally

From the repository root:

```bash
python3 scripts/build_project_site.py
python3 -m http.server 4173 --bind 127.0.0.1 --directory site/dist
```

Open <http://127.0.0.1:4173/>. Rebuild after changing the source, then refresh.
`site/index.html` is a template; serve `site/dist`, not the source directory.

## Publish to GitHub Pages

1. Commit the site, builder, `.gitignore` change, and Pages workflow. Include any
   intended paper updates so the published PDF and page describe the same version.
2. In the repository's **Settings → Pages → Build and deployment → Source**,
   select **GitHub Actions**.
3. Push to `main`, or run **Publish project page** from the Actions tab.

The expected address after successful deployment is:

<https://selvamsriram.github.io/search-api-decision-surface/>

See [GitHub's publishing-source documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

The workflow builds on pull requests and publishes only from branch pushes or
manual runs. Only `site/dist` is uploaded. Draft documents, configuration,
credentials, and raw research artifacts are outside the public site artifact.
The workflow does not need research API credentials or Git LFS downloads.

## Edit the page

- `index.html`: page content and semantic markup.
- `styles.css`: theme, layout, responsive styles, and print styles.
- `main.js`: optional BibTeX copy interaction. Reading and navigation work without JavaScript.
- `assets/citation.bib`: provisional citation using `@misc` until a proceedings or arXiv record is available.
- `assets/favicon.svg`: project icon.

The builder replaces `{{PaperMacro}}` tokens with values from
`paper/figures/numbers.tex` and copies `output/pdf/camera-ready.pdf` to
`site/dist/assets/paper.pdf`. Keep explanatory prose aligned with the paper when
results change. The GroundLM acceptance follows the authors' confirmation;
no workshop year, venue affiliation, DOI, or arXiv identifier is invented.

All local resource URLs are relative, so the output works under a repository
subpath on `github.io` or at a domain root. Generated output is ignored by Git.
