---
name: configure-mcp-servers
description: Install + configure MCP servers in ziee. Use when the user wants to add a tool to the LLM (filesystem, web search, github, etc.) or asks about MCP.
when_to_use: User mentions MCP, adding tools, "how do I let the LLM read files", filesystem access, web search integration, github tools.
metadata: { author: ziee, license: CC0-1.0 }
---

# Configuring MCP servers in ziee

MCP (Model Context Protocol) servers extend the LLM with callable tools. Examples: filesystem access, web search, GitHub API, code execution.

## Two install paths

**From the hub** (recommended): **Hub -> MCP Servers** lists curated, version-pinned MCP servers. Click **Install for me** (user-scope) or **Install for everyone** (system-scope, admin only).

**Manual** (Settings -> MCP Servers -> Add): paste the server's package (npm/pypi) or HTTP URL. Ziee validates the spec before installing.

## After install

Each MCP server is per-user (or system, if admin-installed) by default. To use it in a chat:

1. Open the chat composer.
2. Click the **MCP** chip; toggle servers on/off for this conversation.
3. The LLM sees the server's tools in its next turn. It decides when to call them.

## Built-in servers (always-on)

Ziee ships built-in MCP servers that don't need installation:

- **memory_mcp** -- per-conversation long-term memory (remember / recall / forget).
- **files_mcp** -- read project files attached to the conversation.
- **skill_mcp** -- load installed skills (load_skill, read_skill_file).
- **workflow_mcp** -- run installed workflows as tools.
- **code_sandbox** -- bwrap-isolated bash + Python (when enabled).

These appear in the MCP servers list with an **"Always on"** badge.

## Permissions

System-scope MCP servers (admin-installed) can be restricted to specific user groups via **Settings -> Admin -> MCP Servers -> [server] -> Groups**.

## Troubleshooting

- **Tool didn't fire** -- check the chat's MCP chip; the server may be toggled off for this conversation.
- **Tool returned an error** -- the LLM sees the error in the tool_result; usually it tells you what went wrong.
- **Permission denied on system server** -- your group isn't assigned; ask an admin.
