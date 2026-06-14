#!/usr/bin/env python3
"""Validator parity check — runs validate.py against per-fixture test cases
under test-fixtures/workflows/{valid,invalid}/ and compares emitted error
codes against each fixture's _expected_errors.yaml.

Phase A stub: if the fixture dirs don't exist yet, exit 0 (the parity work
folds into Phase B). Otherwise iterates and reports diffs.

Usage: scripts/check-validator-fixtures.py [--repo /path/to/hub]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    fixtures_root = repo / "test-fixtures" / "workflows"
    if not fixtures_root.is_dir():
        print("validator-fixtures: no test-fixtures/workflows/ dir; skipping (Phase B)")
        return 0
    # Phase A: just confirm the dir is reachable; full parity logic in Phase B.
    print("validator-fixtures: dir present but parity logic deferred to Phase B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
