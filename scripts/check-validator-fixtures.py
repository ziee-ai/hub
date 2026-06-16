#!/usr/bin/env python3
"""Cross-fixture parity check (§4.1 Layer 4) — the validator drift detector.

Walks the shared fixture corpus under test-fixtures/{workflows,skills}/
{valid,invalid}/<name>/, runs validate.py's per-entry validators against each
fixture's source, and compares the emitted error codes against the fixture's
`_expected_errors.yaml`.

`_expected_errors.yaml` is a YAML list of strings. Each entry MUST appear as a
substring of the validator's joined error output for that fixture. A valid
fixture declares an empty list (`[]`) and MUST produce zero errors.

This is the publisher half of the cross-repo parity contract: the consumer
(`ziee-chat`) runs the SAME corpus through its Rust `workflow::validate`
module and asserts the same outcomes. A divergence here OR there means the two
validators silently disagreed — the one thing this check exists to catch.

Exit 0 iff every fixture matches its expectation. Exit 1 on any mismatch.

Usage: scripts/check-validator-fixtures.py [--repo /path/to/hub]
                                           [--schemas schemas/2026-06-12]
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    sys.exit("pyyaml is required (pip install pyyaml)")


def _load_validate_module(repo: Path):
    """Import validate.py as a module so we can call its per-entry validators
    directly (no subprocess, no schemas-dir-must-be-in-cwd dance)."""
    validate_path = repo / "scripts" / "validate.py"
    if not validate_path.is_file():
        sys.exit(f"validate.py not found at {validate_path}")
    spec = importlib.util.spec_from_file_location("validate", str(validate_path))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_expected(fixture_dir: Path) -> list[str]:
    """Read _expected_errors.yaml → list of expected error-code substrings.
    Missing file is treated as 'expect zero errors' (valid fixture)."""
    p = fixture_dir / "_expected_errors.yaml"
    if not p.is_file():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"{p}: _expected_errors.yaml must be a YAML list")
    out: list[str] = []
    for item in data:
        if not isinstance(item, str):
            raise ValueError(f"{p}: every expected-error entry must be a string")
        out.append(item)
    return out


def _check_one(
    validate_mod,
    schemas_dir: Path,
    kind: str,
    fixture_dir: Path,
    rel: str,
) -> list[str]:
    """Validate one fixture dir; compare against expectations. Returns a list
    of failure strings (empty == pass)."""
    failures: list[str] = []
    expected = _load_expected(fixture_dir)

    if kind == "workflow":
        errors = validate_mod.validate_workflow_dir(
            fixture_dir, schemas_dir, fixture_dir.parent, fixture_dir
        )
    elif kind == "skill":
        errors = validate_mod.validate_skill_dir(
            fixture_dir, schemas_dir, fixture_dir.parent, fixture_dir
        )
    else:  # pragma: no cover (defensive)
        return [f"{rel}: unknown fixture kind {kind!r}"]

    joined = "\n".join(errors)

    if not expected:
        # Valid fixture: must produce zero errors.
        if errors:
            failures.append(
                f"{rel}: expected NO errors (valid fixture) but validator "
                f"emitted {len(errors)}:\n      "
                + "\n      ".join(errors)
            )
        return failures

    # Invalid fixture: every expected code must appear, and there must be at
    # least one error (a silently-passing invalid fixture is a regression).
    if not errors:
        failures.append(
            f"{rel}: expected errors {expected!r} but validator emitted NONE "
            f"(the check it targets is missing or was removed)"
        )
        return failures
    for code in expected:
        if code not in joined:
            failures.append(
                f"{rel}: expected error code {code!r} not found in validator "
                f"output:\n      " + "\n      ".join(errors)
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument(
        "--schemas",
        default="schemas/2026-06-12",
        help="Schemas directory relative to --repo (default: schemas/2026-06-12)",
    )
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    schemas_dir = (repo / args.schemas).resolve()
    if not schemas_dir.is_dir():
        print(f"schemas dir not found: {schemas_dir}", file=sys.stderr)
        return 2

    fixtures_root = repo / "test-fixtures"
    if not fixtures_root.is_dir():
        print(
            "validator-fixtures: no test-fixtures/ dir; nothing to check",
            file=sys.stderr,
        )
        return 0

    validate_mod = _load_validate_module(repo)

    # (category folder, fixture kind passed to the validators)
    categories = [
        ("workflows", "workflow"),
        ("skills", "skill"),
    ]

    all_failures: list[str] = []
    checked = 0
    for folder, kind in categories:
        for bucket in ("valid", "invalid"):
            base = fixtures_root / folder / bucket
            if not base.is_dir():
                continue
            for fixture_dir in sorted(p for p in base.iterdir() if p.is_dir()):
                rel = str(fixture_dir.relative_to(repo))
                checked += 1
                try:
                    failures = _check_one(
                        validate_mod, schemas_dir, kind, fixture_dir, rel
                    )
                except Exception as exc:  # pragma: no cover (defensive)
                    failures = [f"{rel}: parity check raised: {exc}"]
                all_failures.extend(failures)

    if all_failures:
        print(
            f"\nvalidator-fixtures: {len(all_failures)} parity failure(s) "
            f"across {checked} fixture(s):",
            file=sys.stderr,
        )
        for f in all_failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(
        f"validator-fixtures: OK — {checked} fixtures match their "
        f"_expected_errors.yaml (workflows + skills, valid + invalid)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
