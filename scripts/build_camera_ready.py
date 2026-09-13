#!/usr/bin/env python3
"""Build the final paper from frozen figures, preserving submitted PDFs."""

from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
BUILD = PAPER / "build/camera-ready"
OUTPUT = ROOT / "output/pdf"
SOURCES = [
    "main_camera_ready.tex", "paper_shared.tex", "appendix_shared.tex",
    "preamble.tex", "refs.bib", "acl.sty", "acl_natbib.bst",
    "figures/numbers.tex", "figures/fig1_pipeline.png",
    "figures/fig2_provider_profiles.png", "figures/fig3_decision_partition.png",
    "figures/fig4_complementarity.png",
]


def main() -> None:
    latexmk = shutil.which("latexmk")
    if not latexmk:
        raise SystemExit("latexmk is required; add your TeX installation to PATH.")
    BUILD.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name in SOURCES:
        target = BUILD / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PAPER / name, target)
    subprocess.run([
        latexmk, "-norc", "-pdf", "-interaction=nonstopmode",
        "-halt-on-error", "-file-line-error", "main_camera_ready.tex",
    ], cwd=BUILD, check=True)
    pdf = OUTPUT / "camera-ready.pdf"
    shutil.copy2(BUILD / "main_camera_ready.pdf", pdf)
    bundle = ROOT / "output/camera-ready-source.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in SOURCES:
            archive.write(BUILD / name, "main.tex" if name == "main_camera_ready.tex" else name)
        archive.write(BUILD / "main_camera_ready.bbl", "main.bbl")
        archive.writestr("README.txt", "Build with: latexmk -pdf main.tex\n"
                        "Frozen, audited figures and number macros are included.\n")
    manifest = {
        "sources": {name: hashlib.sha256((PAPER / name).read_bytes()).hexdigest()
                    for name in SOURCES},
        "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "source_zip_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
    }
    (ROOT / "output/build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Camera-ready PDF: {pdf}\nSource package: {bundle}")


if __name__ == "__main__":
    main()
