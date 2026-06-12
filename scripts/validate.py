#!/usr/bin/env python3
"""Validate every hub source YAML against its JSON Schema and cross-reference rules.

Usage: scripts/validate.py [--repo /path/to/hub] [--schemas schemas/v2]

Exits non-zero on the first error. Intended to run in CI (pr-lint.yml) and
locally before opening a PR.

Source YAMLs carry a build-only `_hub_curation:` block at the top. The
validator extracts that block and validates the *remainder* against the
matching JSON Schema — this is the same payload that will land in
`dist/<type>/<namespace>/<leaf>/<version>.json`. For MCP servers the
remainder is strict server.json (vendored from modelcontextprotocol.io);
for models + assistants it's the ziee v2 shape.

By default validates against `schemas/v2/`. Pass `--schemas schemas/v1` to
exercise the legacy validator during a transition.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    sys.exit("pyyaml is required (pip install pyyaml)")

try:
    from jsonschema import Draft7Validator, Draft202012Validator
    from referencing import Registry, Resource
except ImportError:
    sys.exit("jsonschema + referencing are required (pip install 'jsonschema>=4.21' referencing)")


CATEGORIES = {
    "model": ("models", "model.schema.json"),
    "assistant": ("assistants", "assistant.schema.json"),
    "mcp-server": ("mcp-servers", "mcp-server.schema.json"),
}

# Reverse-DNS pattern: namespace `/` leaf, exactly one `/`.
# Mirrors the official server.json pattern but lower-cases the alphabet
# (ziee-native names are lowercased).
NAME_RE = re.compile(r"^[a-z0-9.-]+/[a-z0-9._-]+$")


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    return data


def split_curation(data: dict) -> tuple[dict, dict]:
    """Returns (curation, manifest_body). `data` is not mutated."""
    body = {k: v for k, v in data.items() if k != "_hub_curation"}
    curation = data.get("_hub_curation") or {}
    if not isinstance(curation, dict):
        raise ValueError("_hub_curation must be a mapping")
    return curation, body


def build_registry(schemas_dir: Path) -> Registry:
    """Register every schema file in `schemas_dir` so internal $ref's resolve."""
    registry = Registry()
    for schema_path in schemas_dir.glob("*.schema.json"):
        contents = json.loads(schema_path.read_text())
        registry = registry.with_resource(
            uri=schema_path.name,
            resource=Resource.from_contents(contents),
        )
    return registry


def build_validator(schemas_dir: Path, schema_name: str):
    """Return a validator instance honoring the schema's declared draft.

    The MCP server.json schema is draft-07; ours are draft-2020-12. We
    pick the validator class based on the schema's `$schema` URL.
    """
    schema = json.loads((schemas_dir / schema_name).read_text())
    registry = build_registry(schemas_dir)
    schema_uri = schema.get("$schema", "")
    if "draft-07" in schema_uri:
        return Draft7Validator(schema, registry=registry)
    return Draft202012Validator(schema, registry=registry)


def validate_category(
    repo: Path,
    schemas_dir: Path,
    category: str,
) -> tuple[set[str], list[str]]:
    folder, schema_name = CATEGORIES[category]
    validator = build_validator(schemas_dir, schema_name)
    names: set[str] = set()
    errors: list[str] = []
    for path in sorted((repo / folder).glob("*.yaml")):
        rel = path.relative_to(repo)
        try:
            data = load_yaml(path)
        except Exception as exc:
            errors.append(f"{rel}: YAML parse error: {exc}")
            continue
        try:
            curation, body = split_curation(data)
        except ValueError as exc:
            errors.append(f"{rel}: {exc}")
            continue
        # Validate the published portion only (the curation block is a
        # build-time concern; never lands in dist/).
        name = body.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            errors.append(
                f"{rel}: missing/invalid name (must match {NAME_RE.pattern})"
            )
            continue
        # Split on the first / to derive <namespace>/<leaf>.
        namespace, _, leaf = name.partition("/")
        if not namespace or not leaf or "/" in leaf:
            errors.append(
                f"{rel}: name must contain exactly one '/' (got {name!r})"
            )
            continue
        if name in names:
            errors.append(f"{rel}: duplicate name within {category}/")
        names.add(name)
        for err in sorted(validator.iter_errors(body), key=lambda e: list(e.absolute_path)):
            path_str = "/".join(str(p) for p in err.absolute_path) or "<root>"
            errors.append(f"{rel}: schema error at {path_str}: {err.message}")
        # Sanity: required curation keys for index emission.
        if not curation.get("title"):
            errors.append(f"{rel}: _hub_curation.title is required")
        if not curation.get("added_at"):
            errors.append(f"{rel}: _hub_curation.added_at is required")
    return names, errors


def validate_cross_refs(repo: Path, names_by_cat: dict[str, set[str]]) -> list[str]:
    """Walk every YAML's dependencies[] list and confirm each entry resolves
    to an existing reverse-DNS name in the matching category. Empty/missing
    dependencies are fine."""
    errors: list[str] = []
    cat_key = {"model": "model", "mcp-server": "mcp-server"}
    for folder in ("models", "assistants", "mcp-servers"):
        for path in sorted((repo / folder).glob("*.yaml")):
            rel = path.relative_to(repo)
            data = load_yaml(path)
            _, body = split_curation(data)
            for dep in body.get("dependencies") or []:
                if not isinstance(dep, dict):
                    continue
                kind = dep.get("kind")
                ref = dep.get("name")
                if kind not in cat_key:
                    # Schema validator already catches unknown kinds.
                    continue
                if not isinstance(ref, str):
                    continue
                if ref not in names_by_cat[cat_key[kind]]:
                    errors.append(
                        f"{rel}: dependencies[] references unknown {kind} name {ref!r}"
                    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument(
        "--schemas",
        default="schemas/v2",
        help="Schemas directory relative to --repo (default: schemas/v2)",
    )
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    schemas_dir = (repo / args.schemas).resolve()
    if not schemas_dir.is_dir():
        print(f"schemas dir not found: {schemas_dir}", file=sys.stderr)
        return 2

    all_errors: list[str] = []
    names_by_cat: dict[str, set[str]] = {}
    for category in CATEGORIES:
        names, errs = validate_category(repo, schemas_dir, category)
        names_by_cat[category] = names
        all_errors.extend(errs)
    all_errors.extend(validate_cross_refs(repo, names_by_cat))

    # `name` uniqueness across categories — installers key on `name` alone.
    seen: dict[str, str] = {}
    for category, names in names_by_cat.items():
        for name in names:
            if name in seen:
                all_errors.append(
                    f"name {name!r} duplicated across categories ({seen[name]} and {category})"
                )
            seen[name] = category

    if all_errors:
        print(f"\n{len(all_errors)} validation error(s):", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    total = sum(len(ns) for ns in names_by_cat.values())
    print(
        f"OK — {total} manifests validated against {schemas_dir.relative_to(repo)} "
        f"({', '.join(f'{c}={len(n)}' for c, n in names_by_cat.items())})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
