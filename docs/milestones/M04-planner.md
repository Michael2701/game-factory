# M04 — Planner Node

Status: complete (2026-10-11) — awaiting user review

## Scope

- `planner_node`: short idea → validated `GameSpec` via `ChatOllama(qwen2.5-coder:14b, temperature=0.2)`.
- Pydantic validation, one repair attempt, structured `NodeError` on failure.
- Runner `scripts/run_planner.py`.

## Done criteria

`python scripts/run_planner.py "A simple game where the player dodges falling blocks for 60 seconds."` prints a valid GameSpec.

## Changes

- New: `agents/llm.py` (`MODEL`, `make_llm`, `extract_json`, `parse_model`), `agents/schemas/node_error.py` (`NodeError`), `agents/prompts/repair.md`, `agents/nodes/planner.py` (`plan_game`, `planner_node`), `scripts/run_planner.py`.
- New: `tests/test_planner.py` (16 tests, 1 gated).
- Changed: `agents/prompts/planner.md` example switched from Block Dodger to "Target Tapper" (see log); `agents/prompts/__init__.py` registers `repair`; `agents/schemas/__init__.py` exports `NodeError`; `tests/test_prompts.py` uses `agents.llm.extract_json` and covers the repair prompt.
- Docs: new `docs/NODES.md`, this file; updated CLAUDE.md, README, ROADMAP, ARCHITECTURE, TESTING, PROMPTS, SCHEMAS.

## Verification log

| Check | Result |
|---|---|
| fast suite | 61 tests OK (3 skipped: LLM) |
| Done-when command (1st run) | exit 0, valid GameSpec in ~15 s — **but a verbatim copy of the Block Dodger example in planner.md** |
| fix: planner example → different game (Target Tapper) | prompt tests green |
| stability: 5 ideas (block dodger ×2, circle clicker, snake, pong) | 5/5 valid on the first call (no repair), 12–16 s each, original content, concrete numeric win/lose |
| repair path with the real model (1st reply forced invalid: bad slug, extra field, missing win_condition) | repaired to a valid GameSpec in 1 repair call |
| `RUN_OLLAMA_TESTS=1` full suite | 61 tests OK in ~74 s; smoke_graph sha256 = baseline |

## Issues / follow-ups

- Prompt examples must not be the validation game (Block Dodger) — the model copies examples nearly verbatim. Keep this in mind for M5+ prompts (task_decomposer/test_writer examples use Block Dodger; revisit when their nodes are built).
- Repair output from a deliberately broken input is valid but terser ("timer reaching 0 wins the game") — acceptable for a repair.
- `GameFactoryState.error` stays a `str` (NodeError JSON prefixed with the node name) to keep M2 schemas unchanged.
