---
name: configure-code-sandbox
description: Enable + configure ziee's bwrap-isolated code execution sandbox. Use when the user wants the LLM to run code, install Python packages, or asks about sandbox flavors.
when_to_use: User asks about code execution, sandbox, bwrap, "can the LLM run my script", flavor downloads, Python in chat.
metadata: { author: ziee, license: CC0-1.0 }
---

# Configuring the code sandbox

The `code_sandbox` module gives the LLM a hardened bash + Python environment via bubblewrap (Linux), libkrun (macOS), or WSL2 (Windows). Disabled by default.

## Enable

1. Install host deps. Linux: `sudo apt install bubblewrap squashfuse fuse3`. Per-distro details: ziee README.
2. **Settings -> Admin -> Code Sandbox** -- toggle on. (Admin only -- sandbox is deployment-wide.)
3. Pick rootfs flavors to pre-fetch:
   - **minimal** (~150 MB) -- bash + coreutils + curl. Fast startup, basic scripting.
   - **full** (~850 MB) -- minimal + Python 3 + pip + Node + npm. Heavy but supports most data work.

## Lazy fetch on first use

If you skip pre-fetch, the first chat turn that triggers a sandbox call downloads the chosen flavor automatically. UI shows a "Fetched 'full' sandbox, 853 MB, 2m 14s" system note. Users who only invoke `minimal` never pay the `full` cost.

## When the LLM uses it

The sandbox is exposed as `execute_command` via the code_sandbox MCP server. The LLM calls it when it needs to compute something (parse JSON, fetch + transform data, run a Python snippet). Each call is per-conversation; workspace stays consistent across calls in one conversation.

## What the sandbox can / can't do

**Can**: HTTP egress (shares host network), write to `/tmp`, install Python packages (`pip install --user`), run subprocesses, read attached conversation files.

**Can't**: read host files outside the workspace, escape to host shell, see other conversations' data, persist files beyond the conversation. `--clearenv` wipes the host environment (no DATABASE_URL, no JWT secret, no API keys leak in).

## Workflows that use sandbox

Workflows with `kind: sandbox` steps need the sandbox enabled. The workflow declares its required `sandbox.flavor`; first-run triggers the flavor fetch if not pre-installed.

## Permissions

- `code_sandbox::environments::manage` -- pre-fetch / evict rootfs flavors.
- `code_sandbox::resource_limits::manage` -- adjust memory / CPU / wall-clock caps.
- Administrators have both by default.
