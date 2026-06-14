---
name: create-workflow
description: Author a new workflow for ziee (declarative YAML DAG with llm / llm_map / sandbox / elicit step kinds). Use when the user wants to create, edit, or test a workflow.
when_to_use: User asks "how do I make a workflow", wants to chain LLM calls, mentions workflow.yaml, asks about steps, kind, llm_map, sandbox steps.
metadata: { author: ziee, license: CC0-1.0 }
---

# Authoring a workflow

Workflows are declarative YAML DAGs. Each step has a `kind`:

| `kind` | What it does |
|---|---|
| `llm` | Single LLM call with templated prompt |
| `llm_map` | Fan-out: N parallel LLM calls over a `for_each` array |
| `sandbox` | Run bash in code_sandbox (any command; declare flavor) |
| `elicit` | Pause + ask the user (JSON Schema for response) |

## Minimum viable workflow

```
my-workflow/
|- workflow.yaml
|- _hub_curation.yaml
`- tests/
    `- basic.yaml
```

`workflow.yaml`:

```yaml
inputs:
  - { name: topic, required: true }
steps:
  - id: summarize
    kind: llm
    prompt: "Summarize {{ inputs.topic }} in 3 bullets."
outputs:
  - { name: summary, from: "{{ summarize.output }}" }
```

`tests/basic.yaml` (required for hub publish):

```yaml
inputs: { topic: "quantum entanglement" }
mocks:
  summarize: "- Bullet 1\n- Bullet 2\n- Bullet 3"
expected_outputs:
  summary: { contains: "Bullet" }
```

## Local dev loop

```bash
# Import:
curl -X POST -F bundle=@./my-workflow http://localhost:8080/api/workflows/import
# Cost preview (no tokens spent):
curl -X POST -d '{"inputs":{"topic":"X"}}' http://localhost:8080/api/workflows/<id>/dry-run
# Run with mocks (no tokens):
curl -X POST -d '{"inputs":{"topic":"X"},"mocks":{"summarize":"..."}}' http://localhost:8080/api/workflows/<id>/run
# Run tests:
curl -X POST http://localhost:8080/api/workflows/<id>/test
```

## Outputs <-> artifacts

- **Outputs** (`outputs:` block): values that flow downstream via `{{ step.output }}`. Captured automatically from step stdout / LLM response.
- **Artifacts** (per-step `artifacts:` field): side files (charts, reports, data) written to `artifacts/<step_id>/`. Auto-collected; surfaced as MCP resources for the LLM + as attachments in chat.

## Best practices

- **Mock every `llm`/`llm_map` step in CI fixtures** (`mode: ci`). Publisher rejects un-mocked CI tests. Add `mode: real_llm` fixtures separately for behavioral validation.
- **`message:` per step** -- author-defined status string shown in the UI timeline ("Researching topic..." beats "Step 3 running").
- **`expose_logs: on_error`** is the default -- log resources surface only on failure, balancing recovery context vs prompt privacy.
- **For long fan-outs**: set `on_error: skip` so individual item failures don't kill the run.

## Publish

PR to `github.com/ziee-ai/hub` under `workflows/io.github.<your-handle>/<workflow-name>/`. Required: source dir + `tests/<name>.yaml` fixtures + `LICENSE` (or SPDX in `_hub_curation.yaml`). Hub CI validates structure + parity; consumer-side smoke tests run behavior against live ziee.
