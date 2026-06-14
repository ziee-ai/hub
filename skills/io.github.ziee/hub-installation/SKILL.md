---
name: hub-installation
description: Browse + install models, assistants, MCP servers, skills, workflows from the ziee hub. Use when the user asks about the hub, installing something from a catalog, or finding tools to extend ziee.
when_to_use: User mentions hub, registry, catalog, browsing tools, installing skills/workflows/MCP servers, "where do I find more X".
metadata: { author: ziee, license: CC0-1.0 }
---

# Installing from the ziee hub

The hub at `https://ziee-ai.github.io/hub` is the central catalog of ziee-compatible artifacts. Five categories:

1. **Models** -- downloadable model weights (GGUF for llama.cpp, HF for transformers)
2. **Assistants** -- preset chat configurations
3. **MCP servers** -- installable tools (filesystem, web search, github, etc.)
4. **Skills** -- Agent Skills-format knowledge bundles
5. **Workflows** -- declarative YAML pipelines

## Browse + install

**Hub** in the sidebar opens the catalog. Filter by category, tag, contributor. Each entry shows:

- Title + description + author + version
- Tags + verified badge if applicable
- Install button

Click **Install for me** (user-scope) or, if admin, choose:

- **Install for me** -- user-scope, only you see it
- **Install for everyone** -- system-scope, visible to all users (group restrictions optional)
- **Install for groups...** -- system-scope + restrict to specific user groups

## Where things land

| Category | After install |
|---|---|
| Model | `Settings -> Models`; available in chat model dropdown |
| Assistant | `/assistants`; available in chat assistant dropdown |
| MCP server | `Settings -> MCP Servers`; toggle per-conversation in chat |
| Skill | `/skills`; auto-available to the LLM via skill_mcp |
| Workflow | `/workflows`; runnable from UI or callable by LLM via workflow_mcp |

## Verifying + uninstalling

**Each category page** lists what's installed. Click an item to view details, run tests (workflows), or uninstall.

## Offline / air-gapped

The seed corpus is bundled in the ziee binary -- works without internet. Browsing the live hub requires HTTPS access to `ziee-ai.github.io`. To pre-populate a private mirror, see ziee's air-gapped deployment docs.

## Authoring + contributing

Want to publish your own skill / workflow / assistant? See:

- `create-skill` skill for skill authoring
- `create-workflow` skill for workflow authoring
- Hub repo `github.com/ziee-ai/hub` for PR submission
