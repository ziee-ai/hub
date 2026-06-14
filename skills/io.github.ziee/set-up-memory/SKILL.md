---
name: set-up-memory
description: Enable + use ziee's per-user persistent memory (mem0-style fact storage with vector retrieval). Use when the user wants the LLM to remember things across conversations.
when_to_use: User mentions "remember this", asks why the LLM forgot something, wants persistent context, or asks about the memory feature.
metadata: { author: ziee, license: CC0-1.0 }
---

# Setting up memory in ziee

Ziee's memory module stores per-user facts in a pgvector-backed database. The LLM injects relevant memories into each chat (via the memory chat extension) and extracts new facts after each turn.

## First-time setup

Memory is **off by default**. Enable in two places:

1. **Admin enables deployment-wide**: **Settings -> Admin -> Memory** -- turn on, pick an embedding model (any provider's embedding model -- small/cheap is fine, `text-embedding-3-small` works).
2. **User enables for themselves**: **Settings -> Memory** -- turn on for your account.

Both must be on. Memory is opt-in at every layer.

## How it works (no user action needed once enabled)

- Before each LLM call: the memory extension fetches the top-K relevant memories for the conversation, prepends them as a system message.
- After each LLM call: a background task extracts new facts from the assistant's response and persists them.
- The LLM can also explicitly call `remember`, `recall`, `forget` via the memory_mcp server.

## Per-conversation override

Conversations have a `memory_mode`: `inherit` (default), `on`, `off`. Override in the conversation settings panel -- useful for ephemeral chats where you don't want facts persisted.

## Viewing + managing memories

**/memories** in the sidebar -- list, search, delete your stored facts. Each memory shows what conversation it came from + when it was last surfaced.

## Privacy

Memories are user-scoped -- never visible across users. They live in your local Postgres. Forgetting is real: deletes are immediate and durable.
