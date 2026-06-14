---
name: configure-llm-providers
description: Configure LLM providers (Anthropic, OpenAI, Groq, Ollama, local) in ziee. Use when the user mentions adding an API key, switching models, getting "no providers configured" errors, or asks how to use a specific model.
when_to_use: User asks about LLM provider setup, API key configuration, "how do I add my key", connecting Ollama, picking a model, or seeing "no model selected" warnings.
metadata:
  author: ziee
  license: CC0-1.0
---

# Configuring LLM providers in ziee

Ziee routes chats through providers configured in **Settings -> LLM Providers**. Each provider is one of:

- **Cloud commercial** -- Anthropic, OpenAI, Google Gemini, Groq, Mistral. Needs an API key from the provider's dashboard.
- **Cloud OpenAI-compatible** -- any endpoint that speaks the OpenAI Chat Completions API (Groq, Together, Fireworks, custom).
- **Local** -- Ollama (`http://localhost:11434`) or `llama.cpp` server. No key.

## Adding a cloud provider

1. Open **Settings -> LLM Providers -> Add Provider**.
2. Pick the provider type from the dropdown.
3. Paste the API key (kept encrypted at rest; never sent to ziee servers -- ziee is local-first).
4. Click **Test connection** -- ziee makes a small list-models call.
5. Save. The provider's models appear in the model picker in the chat composer.

## Adding Ollama (local)

1. Install Ollama (https://ollama.com), pull a model: `ollama pull llama3.1:8b`.
2. **Settings -> LLM Providers -> Add Provider -> Ollama**.
3. Base URL: `http://localhost:11434` (default).
4. Save. Ollama-served models appear in the picker.

## Picking a default

**Settings -> Default Model** picks the model the chat composer starts with. Per-conversation override via the model dropdown in the composer.

## Troubleshooting

- **"No model selected"** -- no default; pick one in Settings or in the composer dropdown.
- **"Invalid API key"** -- re-check the key in Settings -> LLM Providers -> Edit. Some providers (Groq) accept the key but return 401 if the key was revoked.
- **Ollama "connection refused"** -- confirm `ollama serve` is running; check `http://localhost:11434/api/tags` in a browser.

## Cost-aware tips

- For testing workflows: use Groq Llama 3.3 70B (~$0.50/M output tokens) instead of Claude Sonnet (~$15/M).
- For production assistant work: Sonnet quality, GPT-4o sweet spot.
- For fully offline: Ollama with `llama3.1:8b` or `qwen2.5:7b`.
