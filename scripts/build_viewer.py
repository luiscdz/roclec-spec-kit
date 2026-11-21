#!/usr/bin/env python3
"""Compile the viewer interface into ``src/roclec_spec_kit/viewer/static`` (the wheel ships that folder).

Needs Node and the committed ``viewer-ui/package-lock.json`` (installed with ``npm ci``); the published
wheel and ``roclec view`` need neither. ``--check`` rebuilds into a temporary folder and fails when the
committed bundle is stale, which is the CI guard for source/bundle drift.
"""
from __future__ import annotations

import argparse
import filecmp
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "viewer-ui"
STATIC = ROOT / "src/roclec_spec_kit/viewer/static"


def run(*command, cwd=UI):
    subprocess.run(command, cwd=cwd, check=True)


def build(destination: Path):
    if shutil.which("npm") is None:
        raise SystemExit("npm is required to build the viewer interface (Node 20 or newer)")
    run("npm", "ci", "--no-audit", "--no-fund")
    run("npm", "run", "build", "--", "--outDir", str(destination), "--emptyOutDir")


def differences(left: Path, right: Path):
    comparison = filecmp.dircmp(left, right)
    found = [*comparison.left_only, *comparison.right_only, *comparison.diff_files]
    for name in comparison.common_dirs:
        found += [f"{name}/{item}" for item in differences(left / name, right / name)]
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the committed bundle differs from a fresh build")
    args = parser.parse_args()
    if args.check:
        with tempfile.TemporaryDirectory(prefix="roclec-viewer-") as directory:
            fresh = Path(directory) / "static"
            build(fresh)
            stale = differences(STATIC, fresh) if STATIC.is_dir() else ["missing bundle"]
        if stale:
            print("Viewer bundle is stale; run scripts/build_viewer.py:", *stale, sep="\n  ", file=sys.stderr)
            return 1
        print("Viewer bundle is current")
        return 0
    build(STATIC)
    print(f"Built {STATIC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
