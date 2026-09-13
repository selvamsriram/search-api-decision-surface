#!/usr/bin/env python3
"""Copy only validated publication files into a new, empty directory."""
import argparse
from pathlib import Path
import shutil
from check_public_release import ROOT, check


def export(root, destination):
    names = check(root)
    destination.mkdir(parents=True, exist_ok=False)
    for name in names:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)
    check(destination, check_git=False)
    print(f"Exported {len(names)} public files to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="Must not already exist")
    args = parser.parse_args()
    export(ROOT, args.destination.resolve())
