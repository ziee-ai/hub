#!/usr/bin/env python3
"""Validate every hub source YAML against its JSON Schema and cross-reference rules.

Usage: scripts/validate.py [--repo /path/to/hub] [--schemas schemas/2026-06-12]

Exits non-zero on the first error. Intended to run in CI (pr-lint.yml) and
locally before opening a PR.

Source YAMLs carry a build-only `_hub_curation:` block at the top. The
validator extracts that block and validates the *remainder* against the
matching JSON Schema — this is the same payload that will land in
`dist/<type>/<namespace>/<leaf>/<version>.json`. For MCP servers the
remainder is strict server.json (vendored from modelcontextprotocol.io);
for models + assistants it's the ziee hub shape.

By default validates against `schemas/2026-06-12/`. Pass `--schemas schemas/v1` to
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

# Directory-shaped categories (vs the flat YAML categories above). Each entry
# is its own source directory tree, not a single YAML file. Bundles get built
# from these dirs and shipped as tar.gz alongside the manifest JSON.
CATEGORIES_DIR = {
    "skill": {
        "folder": "skills",
        "manifest_schema": "skill.schema.json",
        "body_file": "SKILL.md",  # parsed for frontmatter; body is opaque
        "tests_required": False,
    },
    "workflow": {
        "folder": "workflows",
        "manifest_schema": "workflow.schema.json",
        "body_file": "workflow.yaml",
        "body_schema": "workflow-definition.schema.json",
        "tests_required": True,
        "tests_dir": "tests",
        "test_schema": "test-fixture.schema.json",
    },
}

# Reverse-DNS pattern: namespace `/` leaf, exactly one `/`.
# Mirrors the official server.json pattern but lower-cases the alphabet
# (ziee-native names are lowercased).
NAME_RE = re.compile(r"^[a-z0-9.-]+/[a-z0-9._-]+$")

# Bundle caps — mirrors consumer-side enforcement (hub/bundle.rs)
MAX_BUNDLE_BYTES = 10 * 1024 * 1024
MAX_BUNDLE_FILES = 256
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_DESC_PLUS_WHEN = 1536  # SKILL.md frontmatter description + when_to_use cap

# License posture (§10 risks)
PERMISSIVE_LICENSES = {
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause",
    "CC0-1.0", "CC-BY-4.0", "ISC", "Unlicense", "0BSD",
}
COPYLEFT_LICENSES = {
    "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
    "AGPL-3.0-only", "AGPL-3.0-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later",
}


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


# ----------------------------------------------------------------------------
# Directory-tree categories (skills + workflows)
# ----------------------------------------------------------------------------

# Template ref pattern: {{ step_id.* }} or {{ inputs.* }}, possibly with filters.
TEMPLATE_REF_RE = re.compile(r"\{\{\s*([a-z_][a-zA-Z0-9_]*)\s*(?:\.[^}|\s]+)?[^}]*\}\}")


def parse_skill_md_frontmatter(content_str: str) -> tuple[dict, str]:
    """Parse YAML frontmatter delimited by --- markers.

    Returns (frontmatter_dict, body_str). Raises ValueError if frontmatter
    is missing or malformed.
    """
    lines = content_str.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ValueError("SKILL.md must start with '---' frontmatter delimiter")
    # Find closing ---
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":
            end_idx = i
            break
    if end_idx is None:
        raise ValueError("SKILL.md frontmatter missing closing '---'")
    fm_text = "".join(lines[1:end_idx])
    body = "".join(lines[end_idx + 1:])
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"frontmatter YAML parse error: {exc}")
    if not isinstance(fm, dict):
        raise ValueError("SKILL.md frontmatter must be a YAML mapping")
    return fm, body


def classify_license(spdx: str | None) -> tuple[str, str | None]:
    """Returns (status, message) where status is 'ok' | 'warn' | 'reject'."""
    if not spdx:
        return "reject", "license missing (declare via LICENSE file or _hub_curation.license)"
    if spdx in PERMISSIVE_LICENSES:
        return "ok", None
    if spdx in COPYLEFT_LICENSES:
        return "warn", f"copyleft license {spdx!r} accepted but flagged for maintainer review"
    return "reject", f"license {spdx!r} not in permissive/copyleft allowlist; reject"


def _walk_safe_files(root: Path, rel_root: Path) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Walk root, returning (file_list, errors). Each file_list entry is
    (abs_path, rel_path_within_root). Rejects symlinks, devices, hardlinks,
    and any '..' components."""
    errors: list[str] = []
    files: list[tuple[Path, Path]] = []
    for abs_path in sorted(root.rglob("*")):
        rel = abs_path.relative_to(root)
        rel_display = rel_root / rel
        # Path safety
        if ".." in rel.parts:
            errors.append(f"{rel_display}: path contains '..' (rejected)")
            continue
        if abs_path.is_symlink():
            errors.append(f"{rel_display}: symlinks are rejected")
            continue
        if abs_path.is_dir():
            continue
        if not abs_path.is_file():
            errors.append(f"{rel_display}: not a regular file (rejected)")
            continue
        files.append((abs_path, rel))
    return files, errors


def _check_bundle_caps(
    files: list[tuple[Path, Path]],
    rel_root: Path,
    excluded_rel_paths: set[Path],
) -> list[str]:
    """Enforce bundle size, file count, and per-file caps. Files in
    excluded_rel_paths (e.g. tests/, _hub_curation.yaml, LICENSE) are
    skipped (they don't ship in the bundle)."""
    errors: list[str] = []
    counted = [f for f in files if f[1] not in excluded_rel_paths
               and not any(p == "tests" for p in f[1].parts[:1])]
    if len(counted) > MAX_BUNDLE_FILES:
        errors.append(
            f"{rel_root}: bundle file count {len(counted)} > cap {MAX_BUNDLE_FILES}"
        )
    total = 0
    for abs_path, rel in counted:
        sz = abs_path.stat().st_size
        if sz > MAX_FILE_BYTES:
            errors.append(
                f"{rel_root}/{rel}: single-file size {sz} > cap {MAX_FILE_BYTES}"
            )
        total += sz
    if total > MAX_BUNDLE_BYTES:
        errors.append(
            f"{rel_root}: total bundle bytes {total} > cap {MAX_BUNDLE_BYTES}"
        )
    return errors


def _resolve_license(curation: dict, entry_dir: Path) -> tuple[str | None, bool]:
    """Returns (spdx, has_license_file). spdx may come from curation OR
    the LICENSE file's first line if it's an SPDX-Identifier marker."""
    spdx = curation.get("license")
    license_path = None
    for candidate in ("LICENSE", "LICENSE.md", "LICENSE.txt", "license"):
        p = entry_dir / candidate
        if p.is_file():
            license_path = p
            break
    if not spdx and license_path is not None:
        # Try to extract SPDX-Identifier
        try:
            first_chunk = license_path.read_text(encoding="utf-8", errors="replace")[:512]
        except OSError:
            first_chunk = ""
        m = re.search(r"SPDX-License-Identifier:\s*([A-Za-z0-9.\-+]+)", first_chunk)
        if m:
            spdx = m.group(1)
    return spdx, license_path is not None


def validate_skill_dir(
    repo: Path,
    schemas_dir: Path,
    contributor_dir: Path,
    skill_dir: Path,
) -> list[str]:
    """Validate one skill source dir. Returns list of error strings."""
    rel_root = skill_dir.relative_to(repo)
    errors: list[str] = []

    # _hub_curation.yaml required
    curation_path = skill_dir / "_hub_curation.yaml"
    if not curation_path.is_file():
        errors.append(f"{rel_root}: missing _hub_curation.yaml")
        return errors
    try:
        curation = load_yaml(curation_path)
    except Exception as exc:
        errors.append(f"{rel_root}/_hub_curation.yaml: parse error: {exc}")
        return errors
    if not curation.get("title"):
        errors.append(f"{rel_root}/_hub_curation.yaml: title is required")
    if not curation.get("added_at"):
        errors.append(f"{rel_root}/_hub_curation.yaml: added_at is required")

    # SKILL.md required
    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.is_file():
        errors.append(f"{rel_root}: missing SKILL.md")
        return errors
    try:
        content = skill_md_path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{rel_root}/SKILL.md: read error: {exc}")
        return errors
    try:
        fm, body = parse_skill_md_frontmatter(content)
    except ValueError as exc:
        errors.append(f"{rel_root}/SKILL.md: {exc}")
        return errors
    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errors.append(f"{rel_root}/SKILL.md: frontmatter `description` is required")
    when = fm.get("when_to_use") or ""
    if not isinstance(when, str):
        errors.append(f"{rel_root}/SKILL.md: frontmatter `when_to_use` must be a string")
        when = ""
    combined = (desc or "") + " " + (when or "")
    if len(combined) > MAX_DESC_PLUS_WHEN:
        errors.append(
            f"{rel_root}/SKILL.md: description + when_to_use combined "
            f"({len(combined)}) > cap {MAX_DESC_PLUS_WHEN}"
        )
    # allowed-tools (if present) — accept list-of-strings or space-sep string
    if "allowed-tools" in fm:
        at = fm["allowed-tools"]
        if isinstance(at, str):
            tokens = at.split()
        elif isinstance(at, list):
            tokens = at
        else:
            errors.append(f"{rel_root}/SKILL.md: allowed-tools must be a string or list")
            tokens = []
        for tok in tokens:
            if not isinstance(tok, str) or not tok.strip():
                errors.append(f"{rel_root}/SKILL.md: allowed-tools entry must be a non-empty string")

    # License
    spdx, has_license_file = _resolve_license(curation, skill_dir)
    status, msg = classify_license(spdx)
    if status == "reject":
        errors.append(f"{rel_root}: {msg}")
    elif status == "warn":
        # warnings still printed as errors but tagged; for Phase 1 we accept.
        print(f"  warn: {rel_root}: {msg}", file=sys.stderr)

    # Walk files for size / count / symlink checks
    files, walk_errs = _walk_safe_files(skill_dir, rel_root)
    errors.extend(walk_errs)
    excluded: set[Path] = {Path("_hub_curation.yaml")}
    if has_license_file:
        for candidate in ("LICENSE", "LICENSE.md", "LICENSE.txt", "license"):
            if (skill_dir / candidate).is_file():
                excluded.add(Path(candidate))
                break
    errors.extend(_check_bundle_caps(files, rel_root, excluded))

    return errors


def validate_workflow_dir(
    repo: Path,
    schemas_dir: Path,
    contributor_dir: Path,
    workflow_dir: Path,
) -> list[str]:
    """Validate one workflow source dir. Returns list of error strings."""
    rel_root = workflow_dir.relative_to(repo)
    errors: list[str] = []

    curation_path = workflow_dir / "_hub_curation.yaml"
    if not curation_path.is_file():
        errors.append(f"{rel_root}: missing _hub_curation.yaml")
        return errors
    try:
        curation = load_yaml(curation_path)
    except Exception as exc:
        errors.append(f"{rel_root}/_hub_curation.yaml: parse error: {exc}")
        return errors
    if not curation.get("title"):
        errors.append(f"{rel_root}/_hub_curation.yaml: title is required")
    if not curation.get("added_at"):
        errors.append(f"{rel_root}/_hub_curation.yaml: added_at is required")

    # workflow.yaml required
    wf_path = workflow_dir / "workflow.yaml"
    if not wf_path.is_file():
        errors.append(f"{rel_root}: missing workflow.yaml")
        return errors
    try:
        wf_def = load_yaml(wf_path)
    except Exception as exc:
        errors.append(f"{rel_root}/workflow.yaml: parse error: {exc}")
        return errors

    # Schema-validate the workflow definition
    wf_validator = build_validator(schemas_dir, "workflow-definition.schema.json")
    # Strip $schema for validation
    wf_def_clean = {k: v for k, v in wf_def.items() if k != "$schema"}
    # Re-attach for the validator? The schema declares $schema as a string property,
    # so we leave it in.
    for err in sorted(wf_validator.iter_errors(wf_def), key=lambda e: list(e.absolute_path)):
        path_str = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{rel_root}/workflow.yaml: schema error at {path_str}: {err.message}")

    # Reject mock: in step definitions
    steps = wf_def.get("steps") or []
    step_ids: list[str] = []
    llm_step_ids: list[str] = []
    sandbox_used = False
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        sid = step.get("id")
        if isinstance(sid, str):
            step_ids.append(sid)
        kind = step.get("kind", "llm")
        if kind in ("llm", "llm_map"):
            if isinstance(sid, str):
                llm_step_ids.append(sid)
        if kind == "sandbox":
            sandbox_used = True
        if "mock" in step:
            errors.append(
                f"{rel_root}/workflow.yaml: step[{i}] ({sid}): "
                f"mock: is forbidden in published bundles (dev-only field)"
            )
        # prompt_file resolution
        pf = step.get("prompt_file")
        if pf:
            pf_path = workflow_dir / pf
            if ".." in Path(pf).parts:
                errors.append(
                    f"{rel_root}/workflow.yaml: step[{i}] prompt_file {pf!r} contains '..'"
                )
            elif not pf_path.is_file():
                errors.append(
                    f"{rel_root}/workflow.yaml: step[{i}] prompt_file not found: {pf}"
                )

    # Duplicate step IDs
    seen_ids: set[str] = set()
    for sid in step_ids:
        if sid in seen_ids:
            errors.append(f"{rel_root}/workflow.yaml: duplicate step id {sid!r}")
        seen_ids.add(sid)

    # depends_on referent + cycle check
    deps: dict[str, list[str]] = {}
    for step in steps:
        if not isinstance(step, dict):
            continue
        sid = step.get("id")
        if not isinstance(sid, str):
            continue
        ds = step.get("depends_on") or []
        if not isinstance(ds, list):
            continue
        deps[sid] = [d for d in ds if isinstance(d, str)]
        for d in deps[sid]:
            if d not in seen_ids:
                errors.append(
                    f"{rel_root}/workflow.yaml: step {sid!r} depends_on unknown step {d!r}"
                )
    # Cycle detection (Kahn)
    indeg = {sid: 0 for sid in deps}
    for sid, ds in deps.items():
        for d in ds:
            if d in indeg:
                indeg[sid] += 1
    queue = [s for s, d in indeg.items() if d == 0]
    visited = 0
    while queue:
        n = queue.pop()
        visited += 1
        for sid, ds in deps.items():
            if n in ds:
                indeg[sid] -= 1
                if indeg[sid] == 0:
                    queue.append(sid)
    if visited < len(deps):
        errors.append(f"{rel_root}/workflow.yaml: depends_on graph has a cycle")

    # sandbox.flavor required if any sandbox step
    sandbox_cfg = wf_def.get("sandbox") or {}
    if sandbox_used and not sandbox_cfg.get("flavor"):
        errors.append(
            f"{rel_root}/workflow.yaml: sandbox steps present but top-level sandbox.flavor missing"
        )
    if sandbox_cfg.get("flavor") and not sandbox_used:
        print(
            f"  warn: {rel_root}/workflow.yaml: sandbox.flavor set but no sandbox steps",
            file=sys.stderr,
        )

    # Tests required
    tests_dir = workflow_dir / "tests"
    if not tests_dir.is_dir():
        errors.append(
            f"{rel_root}: missing tests/ dir — workflows must ship regression fixtures; "
            f"see schemas/2026-06-12/test-fixture.schema.json"
        )
    else:
        fixture_paths = sorted(tests_dir.glob("*.yaml")) + sorted(tests_dir.glob("*.yml"))
        if not fixture_paths:
            errors.append(f"{rel_root}/tests: at least one fixture YAML required")
        test_validator = build_validator(schemas_dir, "test-fixture.schema.json")
        for fp in fixture_paths:
            rel_fp = fp.relative_to(repo)
            try:
                fixture = load_yaml(fp)
            except Exception as exc:
                errors.append(f"{rel_fp}: parse error: {exc}")
                continue
            for err in sorted(test_validator.iter_errors(fixture), key=lambda e: list(e.absolute_path)):
                path_str = "/".join(str(p) for p in err.absolute_path) or "<root>"
                errors.append(f"{rel_fp}: schema error at {path_str}: {err.message}")
            mode = fixture.get("mode", "ci")
            if mode == "ci" and llm_step_ids:
                mocks = fixture.get("mocks") or {}
                missing = [s for s in llm_step_ids if s not in mocks]
                if missing:
                    errors.append(
                        f"{rel_fp}: mode: ci requires mocks for every llm/llm_map step; "
                        f"missing: {sorted(missing)}"
                    )

    # License
    spdx, has_license_file = _resolve_license(curation, workflow_dir)
    status, msg = classify_license(spdx)
    if status == "reject":
        errors.append(f"{rel_root}: {msg}")
    elif status == "warn":
        print(f"  warn: {rel_root}: {msg}", file=sys.stderr)

    # Walk files for size / count / symlink checks
    files, walk_errs = _walk_safe_files(workflow_dir, rel_root)
    errors.extend(walk_errs)
    excluded: set[Path] = {Path("_hub_curation.yaml")}
    if has_license_file:
        for candidate in ("LICENSE", "LICENSE.md", "LICENSE.txt", "license"):
            if (workflow_dir / candidate).is_file():
                excluded.add(Path(candidate))
                break
    errors.extend(_check_bundle_caps(files, rel_root, excluded))

    return errors


def validate_category_dir(
    repo: Path,
    schemas_dir: Path,
    category: str,
) -> tuple[set[str], list[str]]:
    """Walk a directory-tree category (skill / workflow). Returns (names, errors)."""
    spec = CATEGORIES_DIR[category]
    folder = spec["folder"]
    base = repo / folder
    names: set[str] = set()
    errors: list[str] = []
    if not base.is_dir():
        return names, errors
    for contributor_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        contributor = contributor_dir.name
        # Optional name pattern check on contributor: should be reverse-DNS-like
        if not re.match(r"^[a-z0-9.-]+$", contributor):
            errors.append(
                f"{contributor_dir.relative_to(repo)}: contributor namespace must match ^[a-z0-9.-]+$"
            )
            continue
        for entry_dir in sorted(p for p in contributor_dir.iterdir() if p.is_dir()):
            leaf = entry_dir.name
            if not re.match(r"^[a-z0-9._-]+$", leaf):
                errors.append(
                    f"{entry_dir.relative_to(repo)}: leaf name must match ^[a-z0-9._-]+$"
                )
                continue
            full_name = f"{contributor}/{leaf}"
            if not NAME_RE.match(full_name):
                errors.append(
                    f"{entry_dir.relative_to(repo)}: name {full_name!r} fails {NAME_RE.pattern}"
                )
                continue
            if full_name in names:
                errors.append(f"{entry_dir.relative_to(repo)}: duplicate name within {category}")
            names.add(full_name)
            if category == "skill":
                errors.extend(validate_skill_dir(repo, schemas_dir, contributor_dir, entry_dir))
            elif category == "workflow":
                errors.extend(validate_workflow_dir(repo, schemas_dir, contributor_dir, entry_dir))
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
        default="schemas/2026-06-12",
        help="Schemas directory relative to --repo (default: schemas/2026-06-12)",
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
    for category in CATEGORIES_DIR:
        names, errs = validate_category_dir(repo, schemas_dir, category)
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
