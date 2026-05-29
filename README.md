# ziee-ai / hub

Catalog of **models**, **assistants**, and **MCP servers** surfaced inside
[ziee-chat](https://github.com/phibya/ziee-chat)'s Hub UI.

Each item is a small YAML manifest committed to this repo. Tagged releases
publish a signed bundle (`hub-vX.Y.Z.tar.gz`) + a flat `index.json` to the
GitHub Releases page; ziee-chat's `HubManager` downloads them, verifies
sha256 + keyless cosign, and renders them in three tabs.

```
models/          5 seeded — Llama 3.1, Phi-3 Mini, Qwen2.5-VL, Llama 3.2 GGUF, Nomic embed
assistants/      3 seeded — Code Reviewer, Creative Writer, Vision Analyst
mcp-servers/     5 seeded — filesystem, github, postgres, brave-search, memory
schemas/v1/      JSON-Schema enforcement (model, assistant, mcp-server, hub_metadata)
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
UI in ziee-chat shows incompatible items collapsed in an "Incompatible (N)"
footer with the install button disabled and a tooltip naming the required
server version. Leaving `min_ziee_version` unset means the item works on
every ziee-chat version that knows about the catalog at all.

## Releases

Maintainer-only:

```bash
git tag -a v0.1.0 -m 'hub v0.1.0 — seed catalog'
git push origin v0.1.0
# release.yml: validate → build index.json → tar → sha256 → cosign keyless → gh release upload
```

The release tag IS the catalog version. ziee-chat pins to a tag at boot,
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

ziee-chat's `HubManager` runs the same two checks in-process via the
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
