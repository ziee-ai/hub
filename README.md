# ziee-ai / hub

Catalog of **models**, **assistants**, and **MCP servers** surfaced inside
[ziee](https://github.com/phibya/ziee-chat)'s Hub UI.

Each item is a small YAML manifest committed to this repo. Tagged releases
publish a signed bundle (`hub.tar.gz`) + a flat `index.json` to the
GitHub Releases page; ziee's `HubManager` downloads them, verifies
sha256 + keyless cosign, and renders them in tabs.

```
models/          locally-runnable LLMs (chat, embedding, vision)
assistants/      pre-configured assistants (system prompt + recommended model)
mcp-servers/     Model-Context-Protocol servers (stdio / http / streamable-http)
schemas/v1/      JSON-Schema enforcement (model, assistant, mcp-server, hub_metadata)
```

## Testing

| Command            | What it does                                                       | Needs                |
|--------------------|--------------------------------------------------------------------|----------------------|
| `just validate`    | Lint every manifest against its JSON Schema. Fast, no Docker.      | python3 + jsonschema |
| `just build-pages` | Build `dist/` locally (same script the workflow runs).             | python3              |
| `just test-pages`  | Execute `.github/workflows/pages.yml` end-to-end via `act`+Docker, then assert the produced `dist/` tree (file count, schemas, reverse-DNS names, entry shape). | Docker Desktop running + [`act`](https://github.com/nektos/act) |

`just test-pages` hard-fails (exit 1) if the Docker daemon is not running.
If `act` is missing it tries `brew install act` once; otherwise it fails
with install instructions. The first run pulls the
`catthehacker/ubuntu:act-latest` image (~1-2 GB) and takes 2-5 minutes;
later runs reuse the cache.

Install requirements on macOS:

```bash
# Docker Desktop: https://www.docker.com/products/docker-desktop
brew install act just
```

## Contributing a new item

1. Pick the right folder (`models/`, `assistants/`, `mcp-servers/`).
2. Copy a seed manifest, rename the file to `<your-id>.yaml`, and edit.
3. Run the validator locally:
   ```bash
   pip install pyyaml 'jsonschema>=4.21' referencing
   python3 scripts/validate.py
   ```
4. Open a PR. `pr-lint.yml` runs the same validator + builds a smoke
   `index.json`. CI must be green before review.

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full submission flow.

## Compatibility

Every manifest carries `hub_metadata.min_ziee_version` (optional). The hub
UI in ziee hides items that require a newer server than the one running,
and the install endpoint rejects them server-side. Leaving
`min_ziee_version` unset means the item works on every ziee version that
knows about the catalog at all.

## Releases

Maintainer-only:

```bash
git tag -a v0.1.0 -m 'hub v0.1.0 — seed catalog'
git push origin v0.1.0
# release.yml: validate → build index.json → tar → sha256 → cosign keyless → gh release upload
```

The release tag IS the catalog version. ziee pins to a tag at boot,
auto-refreshes every 24h, and lets admins force-refresh from the
`/hub` page.

## Verifying an artifact

Artifact filenames are version-less; the tag in the URL carries the
version (which is also embedded inside `index.json` as `hub_version`).

```bash
gh release download v0.1.0 -R ziee-ai/hub
sha256sum -c hub.tar.gz.sha256

cosign verify-blob \
  --bundle hub.tar.gz.cosign.bundle \
  --certificate-identity-regexp \
    '^https://github\.com/ziee-ai/hub/\.github/workflows/release\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  hub.tar.gz
```

ziee's `HubManager` runs the same two checks in-process via the
`sigstore` Rust crate.

## Trust model

- Repo write access is restricted to the ziee-ai team.
- Every PR runs JSON-Schema validation + cross-reference checks (the
  `pr-lint.yml` workflow). Merging without green CI is not possible
  for community contributors.
- Releases sign every artifact with cosign keyless OIDC — the signature
  is bound to this repo's `release.yml` and only valid for tags matching
  semver. A consumer that verifies the cosign identity regex above
  cannot be tricked into accepting an unsigned or differently-signed
  catalog.
- All manifest content is plain text/data — no executable code is
  shipped from this repo. The MCP server entries point at upstream
  binaries (npm packages, Docker images, etc.); installing one runs
  upstream code, not hub code.

## License

Manifests are Apache-2.0. Upstream models / MCP servers retain their
own licenses (declared per manifest).
