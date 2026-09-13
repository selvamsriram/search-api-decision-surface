#!/usr/bin/env python3
"""Build the GitHub Pages project site with paper-derived numbers; stdlib only."""

from __future__ import annotations

import html
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "site"
OUTPUT = SOURCE / "dist"


class SiteReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            identifier = attributes["id"]
            if identifier in self.ids:
                raise ValueError(f"Duplicate HTML id: {identifier}")
            self.ids.add(identifier)
        for key in ("href", "src"):
            if attributes.get(key):
                self.references.append(attributes[key])


def validate_references(page: str) -> None:
    parser = SiteReferences()
    parser.feed(page)
    for reference in parser.references:
        parts = urlsplit(reference)
        if parts.scheme or parts.netloc:
            continue
        if parts.path:
            if parts.path.startswith("/"):
                raise ValueError(f"Use relative URLs for GitHub project pages: {reference}")
            target = (OUTPUT / unquote(parts.path)).resolve()
            if OUTPUT.resolve() not in target.parents or not target.is_file():
                raise ValueError(f"Missing or non-public local resource: {reference}")
        elif parts.fragment and unquote(parts.fragment) not in parser.ids:
            raise ValueError(f"Missing page anchor: {reference}")


def main() -> None:
    macros = dict(re.findall(
        r"\\newcommand\{\\(\w+)\}\{([^{}]*)\}",
        (ROOT / "paper/figures/numbers.tex").read_text(),
    ))
    values = {key: value.replace(r"\%", "%") for key, value in macros.items()}
    values["CITATION"] = (SOURCE / "assets/citation.bib").read_text().strip()
    template = (SOURCE / "index.html").read_text()

    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ValueError(f"Unknown paper metric: {key}")
        return html.escape(values[key])

    page = re.sub(r"\{\{(\w+)\}\}", substitute, template)
    if "{{" in page:
        raise ValueError("Unresolved template expression")
    pdf = ROOT / "output/pdf/camera-ready.pdf"
    if not pdf.read_bytes().startswith(b"%PDF-"):
        raise ValueError("Build the camera-ready PDF before building the site")

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    shutil.copytree(SOURCE / "assets", OUTPUT / "assets", dirs_exist_ok=True)
    shutil.copy2(pdf, OUTPUT / "assets/paper.pdf")
    for name in ("styles.css", "main.js"):
        shutil.copy2(SOURCE / name, OUTPUT / name)
    (OUTPUT / "index.html").write_text(page)
    (OUTPUT / ".nojekyll").touch()
    validate_references(page)
    print(f"Built project site: {OUTPUT}")
    print("Paper metrics resolved; author-visible PDF included; local links verified.")


if __name__ == "__main__":
    main()
