#!/usr/bin/env python3
"""Validate every hub manifest against its JSON Schema and cross-reference rules.

Usage: scripts/validate.py [--repo /path/to/hub]
Exits non-zero on the first error. Intended to run in CI (pr-lint.yml) and
locally before opening a PR.
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
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
except ImportError:
    sys.exit("jsonschema + referencing are required (pip install 'jsonschema>=4.21' referencing)")


CATEGORIES = {
    "model": ("models", "model.schema.json"),
    "assistant": ("assistants", "assistant.schema.json"),
    "mcp-server": ("mcp-servers", "mcp-server.schema.json"),
}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    return data


def build_validator(repo: Path, schema_name: str) -> Draft202012Validator:
    schema = json.loads((repo / "schemas/v1" / schema_name).read_text())
    hub_meta = json.loads((repo / "schemas/v1/_hub_metadata.schema.json").read_text())
    registry = Registry().with_resource(
        uri="_hub_metadata.schema.json",
        resource=Resource.from_contents(hub_meta),
    )
    return Draft202012Validator(schema, registry=registry)


def validate_category(repo: Path, category: str) -> tuple[set[str], list[str]]:
    folder, schema_name = CATEGORIES[category]
    validator = build_validator(repo, schema_name)
    ids: set[str] = set()
    errors: list[str] = []
    for path in sorted((repo / folder).glob("*.yaml")):
        rel = path.relative_to(repo)
        try:
            data = load_yaml(path)
        except Exception as exc:
            errors.append(f"{rel}: YAML parse error: {exc}")
            continue
        item_id = data.get("id")
        if not isinstance(item_id, str) or not ID_RE.match(item_id):
            errors.append(f"{rel}: missing/invalid id (must match {ID_RE.pattern})")
            continue
        if path.stem != item_id:
            errors.append(f"{rel}: filename must equal id (got file={path.stem!r}, id={item_id!r})")
        if item_id in ids:
            errors.append(f"{rel}: duplicate id within {category}/")
        ids.add(item_id)
        for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
            path_str = "/".join(str(p) for p in err.absolute_path) or "<root>"
            errors.append(f"{rel}: schema error at {path_str}: {err.message}")
    return ids, errors


def validate_cross_refs(repo: Path, ids_by_cat: dict[str, set[str]]) -> list[str]:
    errors: list[str] = []
    for path in sorted((repo / "assistants").glob("*.yaml")):
        rel = path.relative_to(repo)
        data = load_yaml(path)
        for ref in data.get("recommended_models") or []:
            if ref not in ids_by_cat["model"]:
                errors.append(f"{rel}: recommended_models references unknown model id {ref!r}")
        for ref in data.get("recommended_mcp_servers") or []:
            if ref not in ids_by_cat["mcp-server"]:
                errors.append(f"{rel}: recommended_mcp_servers references unknown mcp-server id {ref!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    all_errors: list[str] = []
    ids_by_cat: dict[str, set[str]] = {}
    for category in CATEGORIES:
        ids, errs = validate_category(repo, category)
        ids_by_cat[category] = ids
        all_errors.extend(errs)
    all_errors.extend(validate_cross_refs(repo, ids_by_cat))

    # Id uniqueness across categories — installers key on id alone.
    seen: dict[str, str] = {}
    for category, ids in ids_by_cat.items():
        for item_id in ids:
            if item_id in seen:
                all_errors.append(
                    f"id {item_id!r} duplicated across categories ({seen[item_id]} and {category})"
                )
            seen[item_id] = category

    if all_errors:
        print(f"\n{len(all_errors)} validation error(s):", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    total = sum(len(ids) for ids in ids_by_cat.values())
    print(f"OK — {total} manifests validated ({', '.join(f'{c}={len(i)}' for c, i in ids_by_cat.items())})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
