---
name: manage-projects
description: Create/manage chat projects in ziee -- group conversations + attach reference files + set per-project assistant + MCP defaults. Use when the user wants to organize conversations or attach files to multiple chats at once.
when_to_use: User mentions projects, wants to attach files, organize conversations, set defaults for related chats.
metadata: { author: ziee, license: CC0-1.0 }
---

# Managing projects in ziee

A **project** groups conversations under a shared context: project instructions, attached reference files, a default assistant + model, and per-project MCP server settings. Every conversation in a project inherits those.

## Create a project

**Sidebar -> Projects -> +** opens the new-project drawer:

- **Name + description** (free text)
- **Instructions** -- text the LLM sees as a system message in every conversation in this project (up to 64 KiB). Use for: domain context, constraints, persona, ground rules.
- **Default assistant + model** (optional) -- new conversations in this project start with these picked.
- **MCP settings** -- which MCP servers are toggled on for new conversations.

## Attaching files

**Project detail page -> Files tab -> Upload**. Up to 100 files per project. Files are prepended to the first message of every conversation in the project as provider-routed content blocks.

Supported formats: text (md, txt, code), PDF, images. Binary other formats land as base64 attachments.

## Conversation in a project

**New chat in project**: from the projects sidebar widget, hover a project -> "New chat in this project". The conversation inherits the project's instructions + attached files + default model.

**Move existing conversation**: conversation header -> project chip -> pick a project (or "unfiled").

## Sharing patterns

- Projects are user-scoped (per-user; no cross-user sharing in Phase 1).
- For team workflows, use system-scope MCP servers + system-scope assistants/skills instead.

## Limits

- 100 files per project (hard cap; 422 on upload past limit).
- 64 KiB instruction text.
- Project settings snapshot into conversations at create time -- later project edits don't propagate to existing conversations (mcp settings specifically).
