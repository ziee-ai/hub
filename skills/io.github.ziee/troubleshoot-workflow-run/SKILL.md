---
name: troubleshoot-workflow-run
description: Diagnose a failed workflow run using log resources + the error structure. Use when a workflow tool call returned is_error or a run failed.
when_to_use: User reports "my workflow failed", asks why a tool errored, mentions a workflow run that didn't produce expected output, or the LLM just got an is_error tool_result from a workflow tool call.
metadata: { author: ziee, license: CC0-1.0 }
---

# Troubleshooting a failed workflow run

When a workflow tool call returns `is_error: true`, the result carries a rich diagnostic structure. Use it to either:

1. Fix the issue (re-invoke with corrected inputs)
2. Ask the user for clarifying info
3. Escalate to the workflow author (file an issue)

## The error structure

```json
{
  "error": "Step 'extract_per_source' failed: item 3 of 5: LLM returned invalid JSON",
  "failed_step": {
    "id": "...", "kind": "llm_map",
    "items_attempted": 5, "items_succeeded": 4, "items_failed": 1,
    "first_error": {
      "item_index": 3,
      "item_input_preview": "{...}",
      "error_message": "JSON parse: expected ',' at line 5 col 12",
      "raw_output_preview": "{\"claim\":\"foo\",\"source_url\":..."
    }
  },
  "partial_outputs": { "generate_queries": "..." },
  "logs_resource": "ziee://workflow-runs/<id>/logs/extract_per_source"
}
```

## Diagnosis flow

1. **Read `first_error.raw_output_preview`** -- often the most useful single field. If LLM output was truncated mid-JSON, the URL might be malformed; if `items_failed` > 1, the prompt is probably wrong.
2. **`resources/read` the `logs_resource`** for full prompt + raw response. Look for: prompt template that wasn't substituted correctly, malformed `for_each` input, prompt asking for more than the model can produce.
3. **Check `partial_outputs`** -- which steps did succeed? The successful upstream output may reveal what the failing step received.

## Common patterns

- **"JSON parse failed"** on an `llm` / `llm_map` step -> model didn't return JSON despite `output_format: json`. Often: prompt didn't say "return JSON" clearly, or model added prose before/after. Suggest user re-prompt or workflow author tightens the prompt.
- **"item N of M failed"** with `on_error: fail` -> if other items succeeded, this is a content issue with that specific item. With `on_error: skip` the run would have continued; suggest workflow author switch.
- **"sandbox step: exit 1"** -> script error. Read the `stderr` log resource for stack trace.
- **"elicitation timeout"** -> user didn't respond to a `kind: elicit` prompt within `timeout_ms`. Reinvoke; tell user a question is waiting.
- **"per-run token cap exceeded"** -> workflow blew through the budget. Admin can raise `workflow_settings.max_tokens_per_run`; user can pick a cheaper model.

## When to ask the user

After diagnosing, if recovery needs different inputs:
> "I tried researching X but step Y failed because [...]. The URL you mentioned looks malformed -- did you mean Z?"

After user replies, re-invoke the workflow with corrected inputs.

## When to escalate

If the issue is in the workflow itself (bad prompt, missing step, logic bug), point the user at the workflow's source repo:
> "This looks like a bug in the workflow itself -- the `extract_per_source` step's prompt doesn't say to return JSON clearly. You can file an issue at <workflow source URL>."
