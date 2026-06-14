---
name: use-assistants
description: Use + create assistants in ziee -- preset combinations of system prompt + model + parameters. Use when the user wants a specialized chat persona or asks about assistants.
when_to_use: User mentions assistant, wants a persona, asks "what's the difference between chat and assistant", wants to save a prompt as a reusable assistant.
metadata: { author: ziee, license: CC0-1.0 }
---

# Using assistants

An **assistant** is a preset combination of: system prompt (`instructions`), default model, default parameters (temperature, etc.), and recommended MCP servers. Think "saved persona."

## Pick an assistant for a chat

Chat composer -> assistant dropdown. Picking an assistant:

- Sets the system message
- Picks the model (if not overridden)
- Configures parameters
- Suggests MCP servers (you toggle them on)

## Create your own

**Sidebar -> Assistants -> +**:

- **Name + display name** (display shown in dropdown)
- **Instructions** -- the system message (markdown supported)
- **Default model** + parameters
- **Capabilities required** -- declarative hint about what tools this assistant expects (tools, vision, etc.). Documentation only in Phase 1.

## Install from hub

**Hub -> Assistants** browses curated assistants. Same install flow as MCP servers / skills / workflows -- per-user or admin-system.

## Assistant vs raw chat

- **Raw chat**: no system prompt; user is the entire context.
- **Assistant**: system prompt + defaults applied. Useful for repeated workflows (e.g., "code reviewer", "tutor", "translator").

## Assistant vs skill

- **Assistant** = preset chat configuration (what the chat IS).
- **Skill** = procedural knowledge the model loads when relevant (what the chat KNOWS).
- Use both: an assistant defines the persona; skills add domain procedures the LLM uses inside that persona.

## Template assistants

Admin can create template assistants that get auto-cloned to new users on signup. Useful for onboarding ("Getting Started" assistant, "Code Review" assistant, etc.).
