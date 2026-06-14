#!/usr/bin/env python3
"""Reproducibility check — rebuild each skill / workflow bundle twice and assert
identical sha256 across rebuilds.

Run after a successful build-pages.py invocation OR standalone (uses an
ephemeral output dir). Exits non-zero on any sha256 drift.

Usage: scripts/check-reproducibility.py [--repo /path/to/hub]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def load_build_pages_module(repo: Path):
    """Import scripts/build-pages.py as a module (the hyphen blocks regular import)."""
    spec_path = repo / "scripts" / "build-pages.py"
    spec = importlib.util.spec_from_file_location("build_pages", spec_path)
    if spec is None or spec.loader is None:
        sys.exit(f"could not load {spec_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_bundle_shas(out_dir: Path) -> dict[str, str]:
    """Map relative bundle path -> sha256."""
    result: dict[str, str] = {}
    for tarball in sorted(out_dir.rglob("*.tar.gz")):
        rel = tarball.relative_to(out_dir).as_posix()
        result[rel] = sha256_of(tarball)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    build_pages = repo / "scripts" / "build-pages.py"
    if not build_pages.is_file():
        sys.exit(f"scripts/build-pages.py not found at {build_pages}")

    with tempfile.TemporaryDirectory(prefix="ziee-hub-repro-") as td:
        td_path = Path(td)
        out_a = td_path / "dist_a"
        out_b = td_path / "dist_b"
        for out in (out_a, out_b):
            cmd = [
                sys.executable,
                str(build_pages),
                "--repo", str(repo),
                "--out", str(out),
                "--version", "repro",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(result.stdout, file=sys.stdout)
                print(result.stderr, file=sys.stderr)
                sys.exit(f"build-pages.py failed (rc={result.returncode}) for {out}")
        shas_a = collect_bundle_shas(out_a)
        shas_b = collect_bundle_shas(out_b)
        all_keys = sorted(set(shas_a) | set(shas_b))
        if not all_keys:
            print("repro: no bundles found (skills/ + workflows/ empty?); skipping")
            return 0
        mismatches: list[str] = []
        only_a: list[str] = []
        only_b: list[str] = []
        for k in all_keys:
            a = shas_a.get(k)
            b = shas_b.get(k)
            if a is None:
                only_b.append(k)
            elif b is None:
                only_a.append(k)
            elif a != b:
                mismatches.append(f"{k}: {a} != {b}")
        if mismatches or only_a or only_b:
            print(f"repro: FAIL ({len(mismatches)} sha mismatches, "
                  f"{len(only_a)} only in run A, {len(only_b)} only in run B)",
                  file=sys.stderr)
            for line in mismatches:
                print(f"  mismatch: {line}", file=sys.stderr)
            for k in only_a:
                print(f"  only_a:  {k}", file=sys.stderr)
            for k in only_b:
                print(f"  only_b:  {k}", file=sys.stderr)
            return 1
        print(f"repro: OK — {len(all_keys)} bundles identical across rebuilds")
        return 0


if __name__ == "__main__":
    sys.exit(main())
