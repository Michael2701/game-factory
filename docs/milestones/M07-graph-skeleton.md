# M07 — Graph Skeleton

Status: complete (2026-10-11) — awaiting user review

## Scope

First real LangGraph workflow `agents/game_factory_graph.py`: START → planner → task_decomposer → END over `GameFactoryState`. Planning only — no file writing, no game, no game tests.

## Done criteria

`python agents/game_factory_graph.py` runs the graph and prints the parsed GameSpec, the generated TaskPlan and the final state status.

## Changes

- New `agents/game_factory_graph.py`: `build_graph(llm)`, `run(idea, llm)`, `format_state(state)`, `main(argv, llm)`; conditional edge planner → END on `status == error` (decomposer skipped).
- New `tests/test_graph.py` (14 tests, 1 gated).
- `tests/test_planner.py`, `test_task_decomposer.py`, `test_graph.py`: add `tests/` to `sys.path`, so each module also runs alone (`python -m unittest tests.test_graph` failed to import `fakes` before; only `discover` worked).
- Docs: ARCHITECTURE (Graph section), NODES, TESTING, ROADMAP, CLAUDE.md, README, this file.

## Verification log

| Check | Result |
|---|---|
| fast suite | 121 tests OK (5 skipped: LLM); each node/graph test module also passes alone |
| `python agents/game_factory_graph.py` (real model, `caffeinate -i`) | exit 0 in ~46 s; Block Dodger spec (6 hook-based test requirements), 8-task plan, status `tasks_planned` |
| `python agents/game_factory_graph.py "A snake game …"` | exit 0, `snake-game` spec (win: length 10), 8-task plan, `tasks_planned` |
| `RUN_OLLAMA_TESTS=1 caffeinate -i` full suite | 121 tests OK in ~152 s; smoke_graph sha256 = baseline |

## Issues / follow-ups

- Plans are still the same 8-task skeleton with all scenes in one task (M5 note) — decide in M8 whether the coder can handle that.
- `state.error` is a string containing NodeError JSON; fine for now, revisit if the graph needs to branch on error details (M16).
