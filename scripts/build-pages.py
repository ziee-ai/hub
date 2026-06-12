#!/usr/bin/env python3
"""Build the v2 Pages layout for the ziee hub registry.

Output shape (under --out):

  dist/
  ├── index.json                                           # Catalog
  ├── schemas/v2/*.json                                    # copied verbatim
  ├── models/<namespace>/<leaf>/<version>.json             # full manifest
  ├── assistants/<namespace>/<leaf>/<version>.json
  └── mcp-servers/<namespace>/<leaf>/<version>.json

Steps:
  1. Load + validate every YAML under models/, assistants/, mcp-servers/. The
     source YAMLs carry a build-only `_hub_curation:` block — we extract that,
     leave the rest as the published manifest, and validate the published
     remainder against schemas/v2/*.schema.json. Fail the build on any
     schema violation.
  2. (optional, with --ingest-mcp-registry) Paginate
     https://registry.modelcontextprotocol.io/v0/servers, filter to entries
     ziee-chat can actually run (npm/pypi via npx/uvx stdio, OR
     streamable-http/sse remotes), drop docker/oci/mcpb/dnx. Synthesize a
     curation block for index emission.
  3. Merge ziee-native + ingested (collision on `name` → ziee-native wins).
  4. Emit dist/index.json (Catalog), dist/<type>/<namespace>/<leaf>/<version>.json
     (full manifests, with `_hub_curation` stripped), and copy schemas/v2/*.json
     verbatim.

Fail-soft on the MCP registry fetch — if --ingest-mcp-registry is unset OR
the request fails, we skip ingestion and ship a ziee-native-only catalog.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
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


CATEGORIES = [
    ("model", "models", "model.schema.json"),
    ("assistant", "assistants", "assistant.schema.json"),
    ("mcp-server", "mcp-servers", "mcp-server.schema.json"),
]

FOLDER_BY_CAT = {cat: folder for cat, folder, _ in CATEGORIES}

MCP_REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0/servers"
ALLOWED_PKG_REGISTRIES = {"npm", "pypi"}
ALLOWED_RUNTIME_HINTS = {"npx", "uvx"}
# Kebab-case is the official spelling on the wire.
ALLOWED_REMOTE_TYPES = {"streamable-http", "sse"}
DROPPED_PKG_REGISTRIES = {"docker", "oci", "mcpb", "dnx"}

# Reverse-DNS pattern (mirrors validate.py).
NAME_RE = re.compile(r"^[a-z0-9.-]+/[a-z0-9._-]+$")


# ----------------------------------------------------------------------------
# JSON Schema validation
# ----------------------------------------------------------------------------

def build_registry(schemas_dir: Path) -> Registry:
    registry = Registry()
    for schema_path in schemas_dir.glob("*.schema.json"):
        contents = json.loads(schema_path.read_text())
        registry = registry.with_resource(
            uri=schema_path.name,
            resource=Resource.from_contents(contents),
        )
    return registry


def build_validator(schemas_dir: Path, schema_name: str):
    """Return a validator instance honoring the schema's declared draft."""
    schema = json.loads((schemas_dir / schema_name).read_text())
    registry = build_registry(schemas_dir)
    schema_uri = schema.get("$schema", "")
    if "draft-07" in schema_uri:
        return Draft7Validator(schema, registry=registry)
    return Draft202012Validator(schema, registry=registry)


# ----------------------------------------------------------------------------
# Source manifest loading
# ----------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    return data


def split_curation(data: dict) -> tuple[dict, dict]:
    body = {k: v for k, v in data.items() if k != "_hub_curation"}
    curation = data.get("_hub_curation") or {}
    if not isinstance(curation, dict):
        raise ValueError("_hub_curation must be a mapping")
    return curation, body


def summarize(description: str | None, max_len: int = 200) -> str:
    if not description:
        return ""
    line = description.splitlines()[0].strip()
    return line[:max_len]


def split_name(name: str) -> tuple[str, str]:
    """Split a reverse-DNS name on the first `/`. Caller ensures NAME_RE.match()."""
    namespace, _, leaf = name.partition("/")
    return namespace, leaf


def load_ziee_native(
    repo: Path,
    schemas_dir: Path,
) -> tuple[dict[str, list[dict]], list[str]]:
    """Returns (by_category, errors).

    Each entry in `by_category[cat]` is `{"curation": <dict>, "body": <dict>, "__source_path": <str>}`.
    """
    by_category: dict[str, list[dict]] = {cat: [] for cat, _, _ in CATEGORIES}
    errors: list[str] = []

    for category, folder, schema_name in CATEGORIES:
        validator = build_validator(schemas_dir, schema_name)
        names: set[str] = set()
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
            name = body.get("name")
            if not isinstance(name, str) or not NAME_RE.match(name):
                errors.append(
                    f"{rel}: missing/invalid name (must match {NAME_RE.pattern})"
                )
                continue
            if name in names:
                errors.append(f"{rel}: duplicate name within {category}/")
                continue
            names.add(name)
            for err in sorted(validator.iter_errors(body), key=lambda e: list(e.absolute_path)):
                path_str = "/".join(str(p) for p in err.absolute_path) or "<root>"
                errors.append(f"{rel}: schema error at {path_str}: {err.message}")
            if not curation.get("title"):
                errors.append(f"{rel}: _hub_curation.title is required")
            if not curation.get("added_at"):
                errors.append(f"{rel}: _hub_curation.added_at is required")
            by_category[category].append({
                "curation": curation,
                "body": body,
                "__source_path": str(rel),
            })

    return by_category, errors


# ----------------------------------------------------------------------------
# Official MCP registry ingestion
# ----------------------------------------------------------------------------

def fetch_mcp_registry(timeout: int = 30) -> list[dict]:
    """Paginate the official MCP registry. Returns the raw entry list."""
    entries: list[dict] = []
    cursor: str | None = None
    while True:
        params: dict[str, str] = {}
        if cursor:
            params["cursor"] = cursor
        url = MCP_REGISTRY_URL
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "ziee-ai-hub-build/2.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            page = json.loads(resp.read().decode("utf-8"))
        if isinstance(page, list):
            entries.extend(page)
            break
        page_entries = page.get("servers") or page.get("data") or []
        entries.extend(page_entries)
        cursor = (
            page.get("next_cursor")
            or page.get("nextCursor")
            or (page.get("pagination") or {}).get("nextCursor")
        )
        if not cursor:
            break
        if len(entries) > 5000:
            break
    return entries


def filter_ingested(entry: dict) -> dict | None:
    """Return a sanitized {packages, remotes} from `entry` with only ziee-installable
    entries, or None if nothing usable remains.

    Packages must be npm/pypi via npx/uvx with stdio transport.
    Remotes must be streamable-http or sse with a URL.
    """
    packages_in = entry.get("packages") or []
    remotes_in = entry.get("remotes") or []

    packages_out: list[dict] = []
    for pkg in packages_in:
        if not isinstance(pkg, dict):
            continue
        registry_type = pkg.get("registryType") or pkg.get("registry_type")
        runtime_hint = pkg.get("runtimeHint") or pkg.get("runtime_hint")
        transport = pkg.get("transport") if isinstance(pkg.get("transport"), dict) else None
        transport_type = transport.get("type") if transport else None
        if registry_type not in ALLOWED_PKG_REGISTRIES:
            continue
        if runtime_hint not in ALLOWED_RUNTIME_HINTS:
            continue
        if transport_type is not None and transport_type != "stdio":
            continue
        out_pkg = {
            "registryType": registry_type,
            "identifier": pkg.get("identifier") or pkg.get("name"),
            "version": pkg.get("version") or "0.0.0",
            "transport": transport or {"type": "stdio"},
            "runtimeHint": runtime_hint,
        }
        for opt_key in ("runtimeArguments", "packageArguments", "environmentVariables", "registryBaseUrl", "fileSha256"):
            snake = re.sub(r"([A-Z])", r"_\1", opt_key).lower()
            val = pkg.get(opt_key) or pkg.get(snake)
            if val is not None:
                out_pkg[opt_key] = val
        packages_out.append(out_pkg)

    remotes_out: list[dict] = []
    for rem in remotes_in:
        if not isinstance(rem, dict):
            continue
        kind = rem.get("type") or rem.get("transportType")
        # Accept the historical camelCase too, but normalize to kebab-case on output.
        if kind == "streamableHttp":
            kind = "streamable-http"
        if kind not in ALLOWED_REMOTE_TYPES:
            continue
        if not rem.get("url"):
            continue
        out_rem = {"type": kind, "url": rem["url"]}
        if rem.get("headers"):
            out_rem["headers"] = rem["headers"]
        remotes_out.append(out_rem)

    if not packages_out and not remotes_out:
        return None
    return {"packages": packages_out, "remotes": remotes_out}


def synthesize_ingested(entry: dict, filtered: dict) -> dict | None:
    """Build (curation, body) for an ingested MCP entry.

    The body is a strict server.json. Returns None when the entry can't be
    coerced to the official shape (missing name, bad pattern, etc.).
    """
    name = entry.get("name") or ""
    if not isinstance(name, str) or not NAME_RE.match(name):
        return None
    description = entry.get("description") or ""
    version = entry.get("version") or "0.0.0"

    body: dict = {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-09-29/server.schema.json",
        "name": name,
        "description": description[:100] if description else "MCP server.",
        "version": version,
    }
    if isinstance(entry.get("repository"), dict):
        repo_obj = entry["repository"]
        if repo_obj.get("url") and repo_obj.get("source"):
            body["repository"] = {
                "url": repo_obj["url"],
                "source": repo_obj["source"],
            }
            for opt in ("id", "subfolder"):
                if repo_obj.get(opt):
                    body["repository"][opt] = repo_obj[opt]
    if entry.get("websiteUrl"):
        body["websiteUrl"] = entry["websiteUrl"]
    if filtered.get("packages"):
        body["packages"] = filtered["packages"]
    if filtered.get("remotes"):
        body["remotes"] = filtered["remotes"]
    # Preserve any _meta keys from the upstream entry (esp. the registry's
    # own provenance). The frontend may use these later.
    if isinstance(entry.get("_meta"), dict):
        body["_meta"] = entry["_meta"]

    # Synthesize a minimal curation block for index emission.
    _, leaf = split_name(name)
    title_leaf = re.sub(r"[-_]+", " ", leaf).strip()
    title = title_leaf.title() if title_leaf else name

    curation = {
        "title": title,
        "tags": [],
        "verified": False,
        "added_at": dt.date.today().isoformat(),
        "contributor": "mcp-registry",
        "min_ziee_version": None,
        "summary": summarize(description) or "MCP server.",
    }
    return {"curation": curation, "body": body, "__source_path": "<mcp-registry>"}


def ingest_mcp_registry(ziee_names: set[str]) -> tuple[list[dict], dict[str, int]]:
    """Returns (ingested_entries, stats). Stats include kept/dropped counts.
    Silent if the registry is unreachable; the caller can decide to skip.
    """
    stats = {"fetched": 0, "kept": 0, "dropped_uninstallable": 0, "dropped_collision": 0, "dropped_malformed": 0}
    ingested: list[dict] = []

    try:
        raw_entries = fetch_mcp_registry()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"  mcp-registry: fetch failed ({exc}); skipping ingestion", file=sys.stderr)
        return ingested, stats
    except Exception as exc:  # pragma: no cover (defensive)
        print(f"  mcp-registry: unexpected error ({exc}); skipping ingestion", file=sys.stderr)
        return ingested, stats

    stats["fetched"] = len(raw_entries)
    seen: dict[str, dict] = {}

    for entry in raw_entries:
        if not isinstance(entry, dict):
            stats["dropped_malformed"] += 1
            continue
        name = entry.get("name") or ""
        if not isinstance(name, str) or not NAME_RE.match(name):
            stats["dropped_malformed"] += 1
            continue
        filtered = filter_ingested(entry)
        if filtered is None:
            stats["dropped_uninstallable"] += 1
            continue
        if name in ziee_names:
            # ziee-native wins.
            stats["dropped_collision"] += 1
            continue
        # Within ingested, keep first-seen (the registry returns a sorted feed).
        if name in seen:
            stats["dropped_collision"] += 1
            continue
        seen[name] = entry

    for name, entry in seen.items():
        filtered = filter_ingested(entry)
        if filtered is None:
            continue
        synthesized = synthesize_ingested(entry, filtered)
        if synthesized is None:
            stats["dropped_malformed"] += 1
            continue
        ingested.append(synthesized)
        stats["kept"] += 1

    return ingested, stats


# ----------------------------------------------------------------------------
# Pages layout emission
# ----------------------------------------------------------------------------

def index_item(category: str, curation: dict, body: dict) -> dict:
    name = body["name"]
    namespace, leaf = split_name(name)
    version = body.get("version") or "1.0.0"
    manifest_path = f"{FOLDER_BY_CAT[category]}/{namespace}/{leaf}/{version}.json"

    summary = curation.get("summary") or summarize(body.get("description"))

    item: dict = {
        "name": name,
        "category": category,
        "title": curation.get("title") or body.get("display_name") or leaf,
        "summary": summary,
        "tags": curation.get("tags") or body.get("tags") or [],
        "verified": bool(curation.get("verified")),
        "added_at": curation.get("added_at"),
        "min_ziee_version": curation.get("min_ziee_version"),
        "version": version,
        "manifest_path": manifest_path,
    }
    if body.get("_meta"):
        item["_meta"] = body["_meta"]
    return item


def write_manifest(out_dir: Path, category: str, body: dict) -> Path:
    name = body["name"]
    namespace, leaf = split_name(name)
    version = body.get("version") or "1.0.0"
    target = out_dir / FOLDER_BY_CAT[category] / namespace / leaf / f"{version}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Strip internal-only fields before serializing (defensive — `body` already
    # excludes `_hub_curation`).
    body_out = {k: v for k, v in body.items() if not k.startswith("__")}
    target.write_text(json.dumps(body_out, indent=2) + "\n", encoding="utf-8")
    return target


def copy_schemas(schemas_dir: Path, out_dir: Path) -> None:
    target = out_dir / "schemas" / "v2"
    target.mkdir(parents=True, exist_ok=True)
    for schema_path in schemas_dir.glob("*.schema.json"):
        shutil.copy2(schema_path, target / schema_path.name)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--out", required=True, help="Output directory (e.g. dist)")
    parser.add_argument(
        "--version",
        default="2.0.0",
        help="Catalog hub_version (build marker; bumped on schema changes, NOT per entry).",
    )
    parser.add_argument(
        "--ingest-mcp-registry",
        action="store_true",
        help="Fetch + merge entries from registry.modelcontextprotocol.io.",
    )
    parser.add_argument(
        "--schemas",
        default="schemas/v2",
        help="Schemas directory relative to --repo (default: schemas/v2).",
    )
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    out_dir = Path(args.out).resolve()
    schemas_dir = (repo / args.schemas).resolve()

    if not schemas_dir.is_dir():
        print(f"schemas dir not found: {schemas_dir}", file=sys.stderr)
        return 2

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load + validate ziee-native source manifests.
    print(f"build-pages: loading ziee-native manifests from {repo}")
    by_category, errors = load_ziee_native(repo, schemas_dir)
    if errors:
        print(f"\n{len(errors)} schema error(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    counts = {cat: len(entries) for cat, entries in by_category.items()}
    print(f"build-pages: ziee-native counts = {counts}")

    # 2. (optional) Ingest the official MCP registry.
    if args.ingest_mcp_registry:
        ziee_mcp_names = {e["body"]["name"] for e in by_category["mcp-server"]}
        print("build-pages: ingesting registry.modelcontextprotocol.io …")
        ingested, stats = ingest_mcp_registry(ziee_mcp_names)
        print(
            f"build-pages: mcp-registry fetched={stats['fetched']} "
            f"kept={stats['kept']} dropped_uninstallable={stats['dropped_uninstallable']} "
            f"dropped_collision={stats['dropped_collision']} "
            f"dropped_malformed={stats['dropped_malformed']}"
        )
        by_category["mcp-server"].extend(ingested)
    else:
        print("build-pages: --ingest-mcp-registry not set; skipping registry ingestion")

    # 3. Emit per-entry manifests + collect index items.
    items: list[dict] = []
    for category, _, _ in CATEGORIES:
        for entry in by_category[category]:
            curation = entry["curation"]
            body = entry["body"]
            write_manifest(out_dir, category, body)
            items.append(index_item(category, curation, body))

    # Deterministic order by (category, name).
    items.sort(key=lambda it: (it["category"], it["name"]))

    catalog = {
        "schema_version": 2,
        "hub_version": args.version,
        "generated_at": dt.datetime.now(dt.timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
        "items": items,
    }
    index_path = out_dir / "index.json"
    index_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")

    copy_schemas(schemas_dir, out_dir)

    total = len(items)
    print(
        f"build-pages: wrote dist/index.json with {total} items "
        f"(hub_version={args.version}, schema_version=2)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
