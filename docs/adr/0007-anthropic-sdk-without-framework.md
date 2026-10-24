# ADR 0007: The Anthropic SDK directly, with structured output, no RAG framework

- **Status:** accepted
- **Date:** 2026-10-23

## Context

Answering a question takes three calls: embed the question, search, generate. RAG
frameworks (LangChain, LlamaIndex) offer these as components, with their own prompts and
abstractions. The project needs exact control over the prompt, the source escaping and the
output format, and the ability to explain every step.

## Decision

Call the Anthropic SDK directly. The answer uses structured output: a JSON schema
`{answer, insufficient_context}`, so the model can say the passages do not contain the
answer instead of guessing. The stop reason is checked before the content is read: a
refusal or a truncated answer is reported as such, never parsed as a partial answer.
Effort is set explicitly (Claude Opus 5.5 always thinks), and `LLM_MAX_TOKENS` caps the
cost of one answer (2,000; the longest measured answer used about 900).

## Alternatives considered

- **A RAG framework.** Faster to start, but it hides the exact prompt and output handling,
  and adds a large dependency tree to a three-call pipeline.
- **Free-text answers.** Simpler, but nothing would distinguish an answer from an
  admission of ignorance, or from a truncated one.

## Consequences

- Every token sent to the model is visible in one file, and tested.
- Switching provider means writing one more `AnswerModel` implementation (the interface
  already exists for tests).
- Prompt caching is not used yet: the stable prefix is below the minimum cacheable size,
  and the passages change with every question.

## Revisit when

The pipeline grows into multi-step agents with tools, where an orchestration library
earns its abstractions.

## Evidence

[`generation/claude.py`](../../backend/src/uaw/generation/claude.py),
[`generation/answerer.py`](../../backend/src/uaw/generation/answerer.py),
[tests](../../backend/tests/unit/test_claude_model.py)
