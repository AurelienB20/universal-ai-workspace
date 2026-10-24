# ADR 0006: The model cites opaque IDs; the server resolves them

- **Status:** accepted
- **Date:** 2026-10-23

## Context

The value of the system is that answers can be checked. LLMs routinely invent plausible
file paths and line numbers; a prompt asking them not to only reduces how often.

## Decision

Retrieved passages are given to the model under opaque IDs (`S1`, `S2`…), escaped inside
`<source>` tags so that a file cannot close its tag or forge another source. The model may
only write `[Sn]` markers. The server maps each marker to the passage's file, line range
and a permanent GitHub link at the indexed commit, normalizes grouped markers, and removes
any ID it did not provide. Removed IDs are reported in the answer's trace and shown in the
interface.

## Alternatives considered

- **The model writes `file:line` itself, and the server checks it.** A check can only
  reject an invented citation, not fix it, and line ranges are easy to get slightly wrong.
- **No citations, just a list of retrieved files.** It would not tell which sentence comes
  from which passage.

## Consequences

- An invented file name or line number cannot reach users: the code guarantees it.
- A citation points to a whole passage, not to one line inside it.
- Escaping and the "passages are data, not instructions" rule are checked by opt-in tests
  against the real model, with passages that try to override the instructions.

## Revisit when

Finer citations are needed: smaller passages, or sub-passage offsets resolved the same
way.

## Evidence

[`generation/citations.py`](../../backend/src/uaw/generation/citations.py),
[`generation/prompt.py`](../../backend/src/uaw/generation/prompt.py),
[citation tests](../../backend/tests/unit/test_citations.py),
[prompt-injection tests](../../backend/tests/live/test_prompt_injection_live.py)
