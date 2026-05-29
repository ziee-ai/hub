# Contributing

Thanks for adding to the ziee-chat hub. Each entry is a tiny YAML manifest
in one of three folders.

## Quick flow

1. Fork this repo and create a branch.
2. Copy the closest seed manifest, rename it to `<your-id>.yaml`, and edit.
3. Validate locally:
   ```bash
   pip install pyyaml 'jsonschema>=4.21' referencing
   python3 scripts/validate.py
   ```
4. Open a PR using the appropriate template. CI runs the same validator;
   green CI is a precondition for review.

## Picking a folder

| Folder | What goes here | Schema |
|---|---|---|
| `models/` | Locally-runnable LLMs — chat, embedding, vision. Format restricted to safetensors / pytorch / gguf / onnx / mlx. | `schemas/v1/model.schema.json` |
| `assistants/` | Pre-configured chat assistants (system prompt + recommended model + optional MCP servers). | `schemas/v1/assistant.schema.json` |
| `mcp-servers/` | Model-Context-Protocol servers (stdio / http / streamable-http). | `schemas/v1/mcp-server.schema.json` |

## `id` rules

- Lowercase, ASCII, `[a-z0-9._-]`, 2-64 chars.
- The filename must equal the id: `models/my-cool-model.yaml` ⇒ `id: my-cool-model`.
- Globally unique across all three folders (an `id` cannot be both a model and an assistant).

## `hub_metadata`

Every manifest ends with:

```yaml
hub_metadata:
  added_at: '2026-05-29'    # ISO 8601 date; the day you opened the PR
  contributor: phibya        # your GitHub handle (no leading @)
  verified: false            # leave false for community contributions
  min_ziee_version: 0.5.0    # optional; semver; required server version
```

`verified` is flipped to `true` by maintainers for ziee-ai-team-curated
entries during merge.

`min_ziee_version` is optional but recommended whenever your item uses a
feature added in a recent ziee-chat release (e.g. an MCP server requiring
Streamable HTTP transport). Leaving it unset means the item is shown to
every ziee-chat installation that knows about the hub at all.

## Cross-references

- `assistants/*.yaml`'s `recommended_models` entries MUST exist in
  `models/`. The validator rejects unknown ids.
- `assistants/*.yaml`'s `recommended_mcp_servers` entries MUST exist in
  `mcp-servers/`. Same enforcement.
- If your assistant needs a new model or MCP server, add those in the same
  PR (the validator runs all three categories together).

## What gets reviewed

| Check | Where | Required |
|---|---|---|
| Schema validation | `scripts/validate.py` in CI | yes |
| Cross-reference integrity | same | yes |
| ID + filename match | same | yes |
| Description quality + accuracy | maintainer review | yes |
| Upstream availability (the model / MCP exists at the URL claimed) | maintainer review | yes |
| Working examples or demo | maintainer judgement | recommended |

## Releases

Maintainers tag `v0.X.Y` on `main` to publish a new catalog version.
Tag → `.github/workflows/release.yml` → validate → build `index.json` →
tarball → sha256 → cosign keyless → upload to GitHub Releases.

ziee-chat installations refresh the catalog every 24h (or on-demand from
the `/hub` admin page).
