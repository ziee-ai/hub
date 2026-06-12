#!/usr/bin/env bash
# Run the .github/workflows/pages.yml `build` job locally via `act`
# (Docker-backed) and verify the resulting dist/ tree.
#
# Hard-fails (exit 1) if Docker daemon is not running or `act` cannot be
# obtained. No interactive prompts.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# pretty helpers
# ---------------------------------------------------------------------------
log()  { printf '\033[1;34m[test-pages]\033[0m %s\n' "$*" >&2; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n'        "$*" >&2; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n'      "$*" >&2; }
fail() { printf '\033[1;31m[fail]\033[0m %s\n'      "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Phase 1 — environment preconditions
# ---------------------------------------------------------------------------
require_docker() {
  log "checking Docker daemon..."
  if ! command -v docker >/dev/null 2>&1; then
    fail "Docker CLI not found. Install Docker Desktop: https://www.docker.com/products/docker-desktop"
  fi
  if ! docker info >/dev/null 2>&1; then
    fail "Docker daemon not running. Start Docker Desktop and retry."
  fi
  ok "Docker daemon reachable"
}

require_act() {
  log "checking act..."
  if command -v act >/dev/null 2>&1; then
    ok "act found: $(command -v act)"
    return 0
  fi

  warn "act not installed; attempting 'brew install act'..."
  if ! command -v brew >/dev/null 2>&1; then
    fail "neither 'act' nor 'brew' available. Install act manually: https://github.com/nektos/act#installation"
  fi
  if ! brew install act; then
    fail "'brew install act' failed. Install act manually: https://github.com/nektos/act"
  fi
  if ! command -v act >/dev/null 2>&1; then
    fail "act still not on PATH after brew install. Open a new shell or check brew prefix."
  fi
  ok "act installed via brew: $(command -v act)"
}

require_python() {
  log "checking python3..."
  if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not found (need >= 3.10)"
  fi
  local ver
  ver="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  local major minor
  major="${ver%.*}"
  minor="${ver#*.}"
  if (( major < 3 )) || { (( major == 3 )) && (( minor < 10 )); }; then
    fail "python3 >= 3.10 required, found $ver"
  fi
  ok "python3 $ver"
}

require_docker
require_act
require_python

# ---------------------------------------------------------------------------
# Phase 2 — clean baseline
# ---------------------------------------------------------------------------
log "cleaning previous outputs (dist/, .act-artifacts/, .act-run.log)..."
rm -rf dist .act-artifacts .act-run.log
ok "baseline clean"

# ---------------------------------------------------------------------------
# Phase 3 — run the build job via act
# ---------------------------------------------------------------------------
# The first invocation pulls catthehacker/ubuntu:act-latest (~1-2 GB) which
# can take 2-5 minutes. Subsequent runs hit the local cache and finish in
# under a minute.
log "running 'act push -W .github/workflows/pages.yml --job build'"
log "  (first run pulls ~1-2 GB of runner image; expect 2-5 min)"

ACT_ARGS=(
  push
  -W .github/workflows/pages.yml
  --job build
  --container-architecture linux/amd64
  --artifact-server-path "${REPO_ROOT}/.act-artifacts"
  # --bind makes the host workdir the container workdir so dist/ written
  # by the python build step is visible on the host. Without it, act
  # copies the workspace into the container and writes don't propagate.
  --bind
)

# Skip image pull when image is already cached locally — much faster.
# act-22.04 is what act resolves ubuntu-24.04 to by default.
if docker image inspect catthehacker/ubuntu:act-latest >/dev/null 2>&1 \
    || docker image inspect catthehacker/ubuntu:act-22.04 >/dev/null 2>&1; then
  log "runner image already cached; using --pull=false"
  ACT_ARGS+=(--pull=false)
fi

set +e
act "${ACT_ARGS[@]}" 2>&1 | tee .act-run.log
ACT_EXIT="${PIPESTATUS[0]}"
set -e

# The pages.yml workflow ends with two Pages-API steps —
# `actions/configure-pages@v5` and `actions/upload-pages-artifact@v3`
# — which can't run under act locally (no GitHub Pages API token and no
# real Pages site to talk to). They run AFTER our build step, so we
# tolerate act's non-zero exit IFF:
#   - the failure is the configure-pages "token required" error
#   - AND the prior `build pages layout` step succeeded
# Phase 5 then confirms dist/ on the host is the real success gate.
KNOWN_PAGES_API_FAILURE='Parameter token or opts.auth is required'

if [[ "$ACT_EXIT" -eq 0 ]]; then
  ok "act build job finished cleanly (exit 0)"
elif grep -q "$KNOWN_PAGES_API_FAILURE" .act-run.log \
     && grep -q "Success - Main build pages layout" .act-run.log; then
  warn "act exited $ACT_EXIT at the expected configure-pages step"
  warn "  (no local GitHub Pages site; the build steps themselves succeeded)"
else
  fail "act exited $ACT_EXIT for an unexpected reason — see .act-run.log"
fi

# ---------------------------------------------------------------------------
# Phase 4 — locate dist/
# ---------------------------------------------------------------------------
# act bind-mounts the workspace, so the build step's `python3
# scripts/build-pages.py --out dist` should leave dist/ in the repo root.
if [[ ! -d dist ]]; then
  fail "dist/ was not produced in the workspace. Check .act-run.log."
fi
ok "dist/ present at $(pwd)/dist"

# ---------------------------------------------------------------------------
# Phase 5 — assertions on dist/
# ---------------------------------------------------------------------------
verify_dist() {
  log "verifying dist/ shape..."

  [[ -f dist/index.json ]] \
    || fail "missing dist/index.json"
  [[ -f dist/schemas/2026-06-12/mcp-server.schema.json ]] \
    || fail "missing dist/schemas/2026-06-12/mcp-server.schema.json (vendored MCP schema)"
  [[ -f dist/schemas/2026-06-12/model.schema.json ]] \
    || fail "missing dist/schemas/2026-06-12/model.schema.json"
  [[ -f dist/schemas/2026-06-12/assistant.schema.json ]] \
    || fail "missing dist/schemas/2026-06-12/assistant.schema.json"

  local item_count
  item_count="$(python3 -c 'import json; print(len(json.load(open("dist/index.json"))["items"]))')"
  if [[ "$item_count" -lt 18 ]]; then
    fail "expected at least 18 items in index.json, got $item_count"
  fi
  ok "index.json has $item_count items"

  # Reverse-DNS check on every item name (org-prefix/server-id)
  python3 - <<'PY' || fail "reverse-DNS name check failed (see stderr above)"
import json, re, sys
d = json.load(open('dist/index.json'))
RE = re.compile(r'^[a-z0-9.-]+/[a-z0-9._-]+$')
bad = [it['name'] for it in d['items'] if not RE.match(it['name'])]
if bad:
    print('non-reverse-DNS names:', bad, file=sys.stderr)
    sys.exit(1)
PY
  ok "every item has reverse-DNS name"

  # MCP entries: must have packages OR remotes, must NOT carry v1 flat fields.
  python3 - <<'PY' || fail "MCP entry shape check failed (see stderr above)"
import json, glob, sys

FORBIDDEN_V1 = (
    'display_name', 'category', 'tags', 'transport_type',
    'command', 'args', 'url', 'headers', 'required_env',
)

paths = sorted(glob.glob('dist/mcp-servers/*/*/*.json'))
if not paths:
    print('no MCP entries under dist/mcp-servers/*/*/*.json', file=sys.stderr)
    sys.exit(1)

for path in paths:
    e = json.load(open(path))
    if not e.get('packages') and not e.get('remotes'):
        print(f'mcp entry has neither packages nor remotes: {path}', file=sys.stderr)
        sys.exit(1)
    for forbidden in FORBIDDEN_V1:
        if forbidden in e:
            print(f'MCP entry has forbidden v1 field {forbidden!r}: {path}', file=sys.stderr)
            sys.exit(1)

print(f'checked {len(paths)} MCP entries')
PY
  ok "MCP entries pass shape check"

  # Catalog-level sanity: schema_version + hub_version present.
  python3 - <<'PY' || fail "catalog metadata check failed"
import json, sys
d = json.load(open('dist/index.json'))
if d.get('schema_version') != 2:
    print(f'expected schema_version=2, got {d.get("schema_version")!r}', file=sys.stderr)
    sys.exit(1)
if not d.get('hub_version'):
    print('hub_version missing or empty', file=sys.stderr)
    sys.exit(1)
PY
  ok "catalog metadata (schema_version=2, hub_version set)"

  echo
  ok "dist/ verified ($item_count items)"
}

verify_dist

echo
echo "PAGES_WORKFLOW_OK"
