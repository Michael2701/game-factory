# M03 — Prompt Templates

Status: complete (2026-10-11) — awaiting user review

## Scope

- Prompt templates for planner, task_decomposer, coder, test_writer, fixer, reviewer (reference: [PROMPTS.md](../PROMPTS.md)).
- Small strict loader to render them with live JSON schemas.
- Tests, including one gated LLM check that the planner prompt yields a valid GameSpec.

## Done criteria

- Prompt files exist and are clear enough to be used by nodes: same 5 sections, JSON-only output, valid examples, renderable with sample data.

## Changes

- New: `agents/prompts/{planner,task_decomposer,coder,test_writer,fixer,reviewer}.md`, `agents/prompts/__init__.py` (loader). Removed `agents/prompts/.gitkeep`.
- New: `tests/test_prompts.py` (13 tests: 12 fast + 1 gated LLM).
- Docs: new `docs/PROMPTS.md`, this file; updated `CLAUDE.md`, `README.md`, `docs/{ROADMAP,ARCHITECTURE,TESTING}.md`.

## Verification log

| Check | Result |
|---|---|
| `python -m unittest discover -s tests` | 45 tests OK (2 skipped: LLM) |
| First run caught an inconsistent safety phrase in `test_writer.md` | fixed prompt wording |
| Planner prompt × 3 ideas (block dodger, circle clicker, snake), qwen2.5-coder:14b | 3/3 valid GameSpec, 9–14 s each |
| …but circle clicker had win == lose, snake had "a certain length" | added planner rules (exact numbers, distinct win/lose); rerun 3/3 valid and concrete |
| `RUN_OLLAMA_TESTS=1 python -m unittest discover -s tests` | 45 tests OK in ~66 s; smoke_graph sha256 = baseline |

## Issues / follow-ups

- qwen2.5-coder:14b wraps JSON in ```` ``` ```` fences 3/3 times despite instructions → M4 planner node must strip fences (plus the planned one repair attempt).
- `{"changes": [...]}` wrapper model to be defined with the coder node (M8).
- Only the planner prompt is LLM-checked now; other prompts get LLM checks with their nodes (M5, M8, M11, M15, M17).
