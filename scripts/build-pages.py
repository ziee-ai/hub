#!/usr/bin/env python3
"""Build the Pages layout for the ziee hub registry.

Output shape (under --out):

  dist/
  ├── index.json                                           # Catalog
  ├── schemas/2026-06-12/*.json                                    # copied verbatim
  ├── models/<namespace>/<leaf>/<version>.json             # full manifest
  ├── assistants/<namespace>/<leaf>/<version>.json
  └── mcp-servers/<namespace>/<leaf>/<version>.json

Steps:
  1. Load + validate every YAML under models/, assistants/, mcp-servers/. The
     source YAMLs carry a build-only `_hub_curation:` block — we extract that,
     leave the rest as the published manifest, and validate the published
     remainder against schemas/2026-06-12/*.schema.json. Fail the build on any
     schema violation.
  2. (optional, with --ingest-mcp-registry) Paginate
     https://registry.modelcontextprotocol.io/v0/servers, filter to entries
     ziee-chat can actually run (npm/pypi via npx/uvx stdio, OR
     streamable-http/sse remotes), drop docker/oci/mcpb/dnx. Synthesize a
     curation block for index emission.
  3. Merge ziee-native + ingested (collision on `name` → ziee-native wins).
  4. Emit dist/index.json (Catalog), dist/<type>/<namespace>/<leaf>/<version>.json
     (full manifests, with `_hub_curation` stripped), and copy schemas/2026-06-12/*.json
     verbatim.

Fail-soft on the MCP registry fetch — if --ingest-mcp-registry is unset OR
the request fails, we skip ingestion and ship a ziee-native-only catalog.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import re
import shutil
import sys
import tarfile
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

# Directory-shaped categories. Each entry is a source dir tree; bundle the
# rest of the dir (minus _hub_curation.yaml + tests/ + LICENSE) as tar.gz.
CATEGORIES_DIR = [
    ("skill", "skills", "skill.schema.json", "SKILL.md"),
    ("workflow", "workflows", "workflow.schema.json", "workflow.yaml"),
]

FOLDER_BY_CAT = {cat: folder for cat, folder, _ in CATEGORIES}
FOLDER_BY_CAT.update({cat: folder for cat, folder, _, _ in CATEGORIES_DIR})

# Bundle caps (mirror validate.py + consumer-side)
MAX_BUNDLE_BYTES = 10 * 1024 * 1024
MAX_BUNDLE_FILES = 256
MAX_FILE_BYTES = 2 * 1024 * 1024

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
    # Mirror the schemas-dir basename into dist/ so the dated path
    # (e.g. schemas/2026-06-12/) is preserved end-to-end.
    target = out_dir / "schemas" / schemas_dir.name
    target.mkdir(parents=True, exist_ok=True)
    for schema_path in schemas_dir.glob("*.schema.json"):
        shutil.copy2(schema_path, target / schema_path.name)


# ----------------------------------------------------------------------------
# Directory-shaped categories (skill / workflow): bundle + manifest
# ----------------------------------------------------------------------------

# Files/dirs that never ship in the bundle (kept in source for dev/CI).
_EXCLUDED_TOP = {"_hub_curation.yaml", "tests"}
_LICENSE_NAMES = {"LICENSE", "LICENSE.md", "LICENSE.txt", "license"}


def _is_path_safe(rel: Path) -> bool:
    """Reject absolute paths or '..' components."""
    if rel.is_absolute():
        return False
    return ".." not in rel.parts


def _collect_bundle_files(entry_dir: Path) -> list[tuple[Path, Path]]:
    """Walk entry_dir, returning sorted (abs_path, rel_path) pairs that
    SHIP in the bundle. Strips _hub_curation.yaml, tests/, and LICENSE.
    Rejects symlinks. Raises ValueError on safety violations."""
    files: list[tuple[Path, Path]] = []
    for abs_path in sorted(entry_dir.rglob("*")):
        rel = abs_path.relative_to(entry_dir)
        if not _is_path_safe(rel):
            raise ValueError(f"{entry_dir.name}/{rel}: path safety violation")
        if abs_path.is_symlink():
            raise ValueError(f"{entry_dir.name}/{rel}: symlinks rejected")
        # Skip top-level excluded entries
        if rel.parts[0] in _EXCLUDED_TOP:
            continue
        if rel.parts[0] in _LICENSE_NAMES:
            # Don't ship LICENSE in the bundle either — it's referenced via
            # _hub_curation.license. Keeps the bundle minimal.
            continue
        if abs_path.is_dir():
            continue
        if not abs_path.is_file():
            raise ValueError(f"{entry_dir.name}/{rel}: non-regular file rejected")
        files.append((abs_path, rel))
    return files


def _build_bundle(
    category: str,
    entry_dir: Path,
    files: list[tuple[Path, Path]],
) -> tuple[bytes, str, int, int]:
    """Build deterministic tar.gz from `files`. Returns
    (bytes, sha256_hex, size_bytes, file_count).

    Determinism rules:
    - Sorted filenames (caller provides sorted list)
    - mtime=0 on every entry + the gzip header
    - owner = root:root (uid=0, gid=0)
    - For workflows: preserve execute bits on files under scripts/
      (per plan §1 + author guidance — sandbox steps may invoke them).
    - For skills: drop execute bits in Phase 1 (skill scripts deferred).
    """
    # Use a BytesIO + manual gzip wrap so we control the gzip mtime field.
    raw = io.BytesIO()
    # tar.gz is gzip(tar). Build the tar payload first.
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        total = 0
        for abs_path, rel in files:
            data = abs_path.read_bytes()
            if len(data) > MAX_FILE_BYTES:
                raise ValueError(
                    f"{entry_dir.name}/{rel}: file size {len(data)} > cap {MAX_FILE_BYTES}"
                )
            info = tarfile.TarInfo(name=str(rel).replace("\\", "/"))
            info.size = len(data)
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.type = tarfile.REGTYPE
            # Mode policy: 0644 default; preserve exec for workflow scripts/
            mode = 0o644
            if category == "workflow" and rel.parts[:1] == ("scripts",):
                # Preserve owner-execute if the source had it; ensure read for all.
                src_mode = abs_path.stat().st_mode
                if src_mode & 0o100:
                    mode = 0o755
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))
            total += len(data)
    tar_bytes = tar_buf.getvalue()
    # Wrap in gzip with deterministic mtime=0
    raw_buf = io.BytesIO()
    with gzip.GzipFile(fileobj=raw_buf, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(tar_bytes)
    bundle_bytes = raw_buf.getvalue()
    if len(bundle_bytes) > MAX_BUNDLE_BYTES:
        raise ValueError(
            f"{entry_dir.name}: bundle bytes {len(bundle_bytes)} > cap {MAX_BUNDLE_BYTES}"
        )
    if len(files) > MAX_BUNDLE_FILES:
        raise ValueError(
            f"{entry_dir.name}: file count {len(files)} > cap {MAX_BUNDLE_FILES}"
        )
    sha = hashlib.sha256(bundle_bytes).hexdigest()
    return bundle_bytes, sha, len(bundle_bytes), len(files)


def load_ziee_native_dirs(
    repo: Path,
    schemas_dir: Path,
) -> tuple[dict[str, list[dict]], list[str]]:
    """For each directory-shaped category, walk source dirs and prepare
    in-memory entries. Each entry carries `curation`, `entry_dir`, and
    a derived `body` (manifest envelope to be augmented with the bundle
    pointer in the emission pass).
    """
    by_category: dict[str, list[dict]] = {cat: [] for cat, _, _, _ in CATEGORIES_DIR}
    errors: list[str] = []
    for category, folder, _schema, _entry_point in CATEGORIES_DIR:
        base = repo / folder
        if not base.is_dir():
            continue
        names: set[str] = set()
        for contributor_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            contributor = contributor_dir.name
            for entry_dir in sorted(p for p in contributor_dir.iterdir() if p.is_dir()):
                leaf = entry_dir.name
                full_name = f"{contributor}/{leaf}"
                rel = entry_dir.relative_to(repo)
                if not NAME_RE.match(full_name):
                    errors.append(f"{rel}: derived name {full_name!r} fails {NAME_RE.pattern}")
                    continue
                if full_name in names:
                    errors.append(f"{rel}: duplicate name within {category}")
                    continue
                names.add(full_name)
                curation_path = entry_dir / "_hub_curation.yaml"
                if not curation_path.is_file():
                    errors.append(f"{rel}: missing _hub_curation.yaml")
                    continue
                try:
                    curation = load_yaml(curation_path)
                except Exception as exc:
                    errors.append(f"{rel}/_hub_curation.yaml: parse error: {exc}")
                    continue
                # Pull display data from curation; description preferred from SKILL.md
                # frontmatter for skills (read on demand below).
                version = curation.get("version") or "1.0.0"
                description = curation.get("summary") or ""
                if category == "skill":
                    skill_md = entry_dir / "SKILL.md"
                    if skill_md.is_file():
                        try:
                            import re as _re
                            content = skill_md.read_text(encoding="utf-8")
                            # crude frontmatter peek
                            if content.startswith("---\n"):
                                end = content.find("\n---", 4)
                                if end != -1:
                                    fm_text = content[4:end]
                                    fm = yaml.safe_load(fm_text) or {}
                                    if isinstance(fm, dict):
                                        d = fm.get("description")
                                        if isinstance(d, str) and d.strip():
                                            description = d.strip()
                        except Exception:
                            pass
                body = {
                    "$schema": f"/schemas/{schemas_dir.name}/{'skill' if category == 'skill' else 'workflow'}.schema.json",
                    "name": full_name,
                    "version": version,
                    "description": description,
                    "tags": curation.get("tags") or [],
                }
                license_spdx = curation.get("license")
                if license_spdx:
                    body["license"] = license_spdx
                if curation.get("contributor"):
                    body["author"] = curation["contributor"]
                by_category[category].append({
                    "curation": curation,
                    "body": body,
                    "entry_dir": entry_dir,
                    "category": category,
                    "__source_path": str(rel),
                })
    return by_category, errors


def write_dir_bundle(
    out_dir: Path,
    category: str,
    entry: dict,
) -> dict:
    """Build bundle, write tar.gz + manifest.json. Mutates entry['body']
    in place to attach the bundle pointer. Returns the body."""
    entry_dir: Path = entry["entry_dir"]
    body: dict = entry["body"]
    files = _collect_bundle_files(entry_dir)
    bundle_bytes, sha, size, fcount = _build_bundle(category, entry_dir, files)

    folder = FOLDER_BY_CAT[category]
    name = body["name"]
    namespace, leaf = split_name(name)
    version = body["version"]
    rel_bundle = f"{folder}/{namespace}/{leaf}/{version}.tar.gz"
    target_dir = out_dir / folder / namespace / leaf
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / f"{version}.tar.gz").write_bytes(bundle_bytes)

    entry_point = "SKILL.md" if category == "skill" else "workflow.yaml"
    body["bundle"] = {
        "url": rel_bundle,
        "sha256": sha,
        "size_bytes": size,
        "file_count": fcount,
        "entry_point": entry_point,
    }
    body.setdefault("dependencies", [])

    target_manifest = target_dir / f"{version}.json"
    body_out = {k: v for k, v in body.items() if not k.startswith("__")}
    target_manifest.write_text(json.dumps(body_out, indent=2) + "\n", encoding="utf-8")
    return body


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
        default="schemas/2026-06-12",
        help="Schemas directory relative to --repo (default: schemas/2026-06-12).",
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

    # 3b. Directory-shaped categories (skills + workflows).
    dir_by_category, dir_errors = load_ziee_native_dirs(repo, schemas_dir)
    if dir_errors:
        print(f"\n{len(dir_errors)} dir-category load error(s):", file=sys.stderr)
        for err in dir_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    for category, _, _, _ in CATEGORIES_DIR:
        for entry in dir_by_category[category]:
            try:
                body = write_dir_bundle(out_dir, category, entry)
            except ValueError as exc:
                print(f"  ERROR: bundle build failed: {exc}", file=sys.stderr)
                return 1
            items.append(index_item(category, entry["curation"], body))
        print(f"build-pages: {category} bundles built = {len(dir_by_category[category])}")

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
