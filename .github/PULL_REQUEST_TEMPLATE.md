<!--
Thanks for contributing! A few quick things:

1. CI (pr-lint.yml) must be green before review.
2. Fill in the sections below — they help reviewers move fast.
3. If you're adding multiple items in one PR, list each one.
-->

## What's in this PR

<!-- Brief: "Adds the foo-mcp MCP server" or "Adds 3 new code-assistant variants" -->

## Items added / changed

| Category | id | file |
|---|---|---|
| model / assistant / mcp-server | `your-id` | `<folder>/your-id.yaml` |

## Compatibility

<!--
If you set `min_ziee_version`, paste the reason here (e.g. "uses Streamable
HTTP transport, available since ziee-chat 0.5.0"). If you left it unset,
just write "compatible with all hub-aware ziee-chat versions".
-->

## I confirm

- [ ] `python3 scripts/validate.py` passes locally
- [ ] Each id is unique and matches its filename
- [ ] For MCP servers: I've tested the transport against a real MCP client
- [ ] For models: the `repository_path` resolves on the upstream registry
- [ ] For assistants: every id in `recommended_models` / `recommended_mcp_servers` exists in this repo
- [ ] `hub_metadata.added_at` is today's date, `contributor` is my GitHub handle, `verified: false`
