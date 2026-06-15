---
name: effective-prompting
description: Write clearer, more reliable prompts for any LLM. Use when the user's request is vague, a model's answer is off-target or inconsistent, or the user asks how to phrase a prompt, reduce hallucination, or get structured output.
when_to_use: User asks "how should I prompt this", "why is the model ignoring my instructions", wants more consistent or structured (JSON/table) output, mentions prompt engineering, few-shot examples, or the model is rambling / making things up.
metadata: { author: ziee, license: CC0-1.0 }
---

# Writing effective prompts

Generic, model-agnostic techniques for getting reliable results from any LLM.

## Start with the four ingredients

1. **Role / context** — who the model is and what it's working on ("You are a senior Rust reviewer looking at a PR diff").
2. **Task** — one clear, specific instruction. Split unrelated asks into separate prompts.
3. **Constraints** — length, tone, what to avoid, edge cases to handle.
4. **Output format** — exactly how the answer should be shaped.

## Make the output shape explicit

Vague prompts get vague answers. If you need structure, say so and show it:

> Return a JSON array of objects with keys `title` (string) and `url` (string). No prose before or after.

For prose, specify length and form ("3 bullets, ≤15 words each").

## Show, don't just tell (few-shot)

When the format or judgement is subtle, give 1–3 examples of input → desired
output. Examples constrain the model far more reliably than adjectives.

## Reduce hallucination

- Tell it what to do when it doesn't know: *"If the sources don't cover X, say 'not stated' — do not guess."*
- Ground it: paste the source text and instruct it to answer **only** from that text.
- Ask for citations or quotes so claims are checkable.

## Common fixes

| Symptom | Fix |
|---|---|
| Ignores an instruction | Move the most important constraint to the end; make it imperative + specific. |
| Inconsistent format | Provide an explicit schema + one example; lower temperature. |
| Rambles | Add a hard length limit and "no preamble". |
| Makes things up | Add "say 'unknown' if not in the provided text"; ground with sources. |
| Wrong level of detail | State the audience ("explain for a beginner" / "for an expert"). |

## Iterate

Treat the first answer as a draft. Note exactly what was wrong, add a
constraint that prevents it, and re-run — small, targeted edits beat
rewriting the whole prompt.
