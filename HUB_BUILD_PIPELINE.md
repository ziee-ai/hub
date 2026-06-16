# Hub build pipeline

How source files in this repo become the published Pages catalog at
`https://ziee-ai.github.io/hub/`.

## Layout

```
schemas/2026-06-12/         JSON Schemas (single source of truth)
models/<file>.yaml          Flat YAML, one per model
assistants/<file>.yaml      Flat YAML, one per assistant
mcp-servers/<file>.yaml     Flat YAML, one per MCP server
skills/<ns>/<leaf>/         Directory tree (SKILL.md + references/ + ...)
workflows/<ns>/<leaf>/      Directory tree (workflow.yaml + prompts/ + scripts/ + tests/)
scripts/validate.py         Structural validator (CI gate)
scripts/build-pages.py      Emits dist/ for GitHub Pages
```

## The two source shapes

| Categories | Shape | How they ship |
|---|---|---|
| `models`, `assistants`, `mcp-servers` | Flat `<file>.yaml` per entry, one manifest per file. `_hub_curation:` block at the top is stripped at build time. | Single `<version>.json` published per entry. |
| `skills`, `workflows` | Directory tree per entry: `_hub_curation.yaml` + body files + (workflows only) `tests/`. | `<version>.tar.gz` bundle + `<version>.json` manifest pointing at the bundle (sha256, size, file count). |

## Strip rules — bundle categories

When building a skill / workflow bundle, `build-pages.py` excludes:

- `_hub_curation.yaml` — curation block, never published.
- `tests/` — workflow regression fixtures, never published. Authors use
  these locally + via `POST /api/workflows/{id}/test` after dev import.
- `LICENSE` / `LICENSE.md` / `LICENSE.txt` / `license` — the SPDX
  identifier from `_hub_curation.license` lands in the manifest;
  shipping the full text would bloat every bundle and the spec only
  needs the identifier.

Everything else round-trips into the bundle byte-for-byte.

## Determinism

Bundles are tar.gz with `mtime=0`, `uid=0`, `gid=0`, sorted filenames,
gzip header `mtime=0`. This makes sha256 reproducible across rebuilds —
verified by `scripts/check-reproducibility.py` in CI.

File mode policy:

- Skills: 0644 across the board. Skill `scripts/` execution is a
  Phase 2 feature.
- Workflows: 0755 on files under `scripts/` if they were executable in
  the source tree; 0644 otherwise. Sandbox steps may invoke them.

## Validation (CI gate via `workflow-tests.yml`)

`scripts/validate.py` runs every schema + structural check:

- Manifest YAMLs validate against their JSON Schemas.
- `name` is unique within a category AND across all categories.
- `dependencies[]` refs resolve to known names.
- Skills: `SKILL.md` frontmatter is parsed; `description` is required;
  `description + when_to_use` capped at 1536 chars.
- Workflows: `workflow.yaml` validates against
  `workflow-definition.schema.json`; `depends_on` is cycle-free;
  `prompt_file` paths resolve; `mock:` is REJECTED in step defs (dev-only).
- Workflows: `tests/` is REQUIRED with at least one fixture YAML;
  every fixture validates against `test-fixture.schema.json`; for
  `mode: ci` fixtures, `mocks` must cover every `llm`/`llm_map` step.
- License: required (`_hub_curation.license` OR LICENSE file with
  SPDX-Identifier marker); permissive licenses pass, copyleft is
  flagged (warn) and accepted, anything else is rejected.
- Size + file-count caps: 10 MiB total, 256 files, 2 MiB per file.
  Symlinks + `..` paths rejected.

## Reproducibility check

`scripts/check-reproducibility.py` rebuilds every bundle from source
twice and asserts identical sha256. Catches any non-determinism that
would break consumer-side sha256 verification.

## Validator fixture parity (Phase B)

`scripts/check-validator-fixtures.py` is a stub today; Phase B fills
in cross-fixture parity tests so the publisher's validator agrees with
the consumer's validator on a known corpus of valid + invalid examples.

## Author trust-but-verify (workflows + skills)

The hub's CI can only check structure. Behavioral validation is
author + reviewer responsibility:

- **Author**: run `wf test ./workflows/<contrib>/<name>/` against a
  local ziee instance and paste the output into the PR template.
- **Reviewer**: run the same `wf test` locally before approving,
  especially for new contributors or substantial changes.
- **Maintainer (CODEOWNERS)**: gates merge on a maintainer for any
  `workflows/**` change.

## Workflow author contract

- `tests/` directory is REQUIRED. Ship at least one fixture (`tests/basic.yaml`
  is convention).
- For each `mode: ci` fixture: `mocks` must cover EVERY `llm` and
  `llm_map` step in `workflow.yaml`. Validator rejects un-mocked CI
  fixtures with the missing step IDs.
- For `mode: real_llm` fixtures: ship them too if the workflow has
  behavioral edges worth catching against a real model. These run in
  a separate label-gated CI job (not every PR).
- `mock:` MUST NOT appear in step definitions in `workflow.yaml` —
  mocks live in `tests/*.yaml` only. Validator rejects on encounter.
- If any step is `kind: sandbox`, top-level `sandbox.flavor` is
  REQUIRED. Pick `minimal` (~150 MB) unless the script needs Python
  / Node / heavy tooling, then pick `full` (~850 MB).
- Use `message:` per step so the UI timeline renders something better
  than "Step 3 running". Use `expose_logs: on_error` (the default) to
  expose diagnostic resources only on failure.

## Dev import workflow

Workflows under active development can be imported with `is_dev: true`:

```bash
curl -X POST -F bundle=@./my-workflow http://localhost:8080/api/workflows/import
```

In dev mode:

- `mock:` keys ARE honored in step defs (one-off testing without burning
  tokens).
- Re-import overwrites without bumping versions.
- `POST /api/workflows/{id}/test` runs every fixture under `tests/`.

Once happy, drop `mock:` from `workflow.yaml`, open a PR. The hub CI
validator will reject the bundle if any `mock:` survived.
