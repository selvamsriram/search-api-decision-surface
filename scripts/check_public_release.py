#!/usr/bin/env python3
"""Check the publication allowlist, result schemas/hashes, and paper package."""
import argparse
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def public_files(root):
    names = (root / "release/public-files.txt").read_text().splitlines()
    if len(names) != len(set(names)) or names != sorted(names):
        raise ValueError("Publication allowlist must be sorted and unique")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or str(path) != name:
            raise ValueError(f"Unsafe publication path: {name}")
        if (name.startswith((".git/", ".camera-ready-local/", "data/traces/", "data/page_cache/", "review/", "docs/archive/"))
                or name == ".env"
                or (name.startswith("results/") and not name.startswith("results/released/"))):
            raise ValueError(f"Private path on publication allowlist: {name}")
        candidate = root / name
        if not candidate.is_file() or candidate.is_symlink() or root.resolve() not in candidate.resolve().parents:
            raise ValueError(f"Missing or indirect publication file: {name}")
    return names


def check(root, check_git=True):
    names = public_files(root)
    if check_git:
        tracked = set(subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")) - {""}
        extra = tracked - set(names)
        if extra:
            raise ValueError(f"Tracked files outside publication allowlist: {sorted(extra)}")
    for name in names:
        if (root / name).read_bytes().startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise ValueError(f"LFS pointer in public release: {name}")
    if "filter=lfs" in (root / ".gitattributes").read_text():
        raise ValueError("Public release must not enable LFS tracking")
    results = root / "results/released"
    hashes = json.loads((results / "hashes.json").read_text())
    schema = json.loads((root / "release/result-columns.json").read_text())
    if set(hashes) != set(schema):
        raise ValueError("Result manifest and schema differ")
    if {p.name for p in results.glob("*.csv")} != set(hashes):
        raise ValueError("Unexpected result CSV")
    for name, expected in hashes.items():
        data = (results / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Result changed; review and regenerate manifest: {name}")
        with (results / name).open(newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != schema[name]:
                raise ValueError(f"Unexpected result columns: {name}")
            for row in reader:
                if None in row or any(v is None or len(v) > 160 or "http://" in v or "https://" in v for v in row.values()):
                    raise ValueError(f"Unexpected free text or malformed row: {name}")
    manifest = json.loads((root / "output/build-manifest.json").read_text())
    for name, expected in manifest["sources"].items():
        if hashlib.sha256((root / "paper" / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Paper source differs from built artifact: {name}")
    for name, key in [("pdf/camera-ready.pdf", "pdf_sha256"), ("camera-ready-source.zip", "source_zip_sha256")]:
        if hashlib.sha256((root / "output" / name).read_bytes()).hexdigest() != manifest[key]:
            raise ValueError(f"Paper artifact hash mismatch: {name}")
    expected_members = {"main.tex" if x == "main_camera_ready.tex" else x for x in manifest["sources"]} | {"main.bbl", "README.txt"}
    with zipfile.ZipFile(root / "output/camera-ready-source.zip") as archive:
        if set(archive.namelist()) != expected_members or len(archive.namelist()) != len(expected_members):
            raise ValueError("Unexpected paper source ZIP contents")
    print(f"Public release check passed: {len(names)} files, {len(hashes)} result CSVs; paper hashes and ZIP verified.")
    return names


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--no-git", action="store_true", help="Validate an exported directory without a Git index")
    args = parser.parse_args()
    check(args.root.resolve(), not args.no_git)
