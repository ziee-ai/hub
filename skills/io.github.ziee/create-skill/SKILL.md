---
name: create-skill
description: Author a new skill for ziee (Agent Skills standard -- works in Claude Code too). Use when the user wants to create, edit, or share a skill.
when_to_use: User asks "how do I make a skill", wants to create knowledge for the LLM, asks about SKILL.md, mentions Agent Skills spec.
metadata: { author: ziee, license: CC0-1.0 }
---

# Authoring a skill

Skills are directory bundles with a `SKILL.md` at root, following the [Agent Skills open standard](https://agentskills.io). Same format works in ziee + Claude Code.

## Minimum viable skill

```
my-skill/
|- SKILL.md
`- references/         # optional
    `- advanced.md
```

`SKILL.md`:

````markdown
---
name: my-skill
description: One-sentence summary + when-to-use trigger. The LLM uses this to decide when to load the skill.
when_to_use: Extra hint phrases. Combined with description; capped at 1536 chars.
---

# Body
Procedural instructions the model follows when this skill is loaded.

See [references/advanced.md](references/advanced.md) for details.
````

## Distribute

**Local install for dev**: `POST /api/skills/import` (multipart upload of the dir as a tarball) -- installs with `is_dev: true` for fast iteration.

**Publish to hub**: open a PR in `github.com/ziee-ai/hub` under `skills/io.github.<your-handle>/<skill-name>/`. Required: `_hub_curation.yaml` (title, tags, contributor, summary, license) + `SKILL.md` + (optional) `references/`. Publisher CI validates schema + license; merged PRs publish to hub via GitHub Pages.

## Best practices

- **Description is critical**: the LLM only sees this in the "available skills" listing -- it decides whether to `load_skill` based on this string. Make it specific: "Use when X" not "Helpful guide."
- **Keep SKILL.md focused**: 200-500 words for the main body. Heavy detail goes in `references/` files, which the LLM reads on demand.
- **`allowed-tools:`** (kebab-case) -- Phase 2 enforcement; for now, documents intent.
- **No private prompts**: if your SKILL.md leaks proprietary content, set `expose_logs: never` to keep it from log resources.

## Cross-tool compat

A ziee skill bundle dropped into `~/.claude/skills/` works in Claude Code. The Agent Skills standard is the wire format; both tools consume it.
