# M05 — Task Decomposer Node

Status: complete (2026-10-11) — awaiting user review

## Scope

- `task_decomposer_node`: GameSpec → validated, ordered TaskPlan. Plans only — never writes files.
- Shared parse → check → repair → NodeError loop extracted for all LLM nodes.
- Runner `scripts/run_task_decomposer.py`.

## Done criteria

Given a sample GameSpec, the node returns a valid ordered TaskPlan.

## Changes

- `agents/llm.py`: new `format_errors`, `invoke_structured(llm, node, prompt, model, schema, check=None)`.
- `agents/nodes/planner.py`: now uses `invoke_structured` (behaviour unchanged; all planner tests pass untouched apart from the FakeLLM import).
- New `agents/nodes/task_decomposer.py`: `check_plan` (slug match, 5–12 tasks, required kinds config/code/test_hooks/tests/build/run_tests, build/run_tests after all code), `decompose`, `task_decomposer_node`.
- `agents/prompts/task_decomposer.md`: example switched from Block Dodger to Target Tapper (M4 lesson).
- New `scripts/run_task_decomposer.py` (default sample Block Dodger spec, `--spec file.json`).
- New `tests/fakes.py` (shared `FakeLLM`), `tests/test_task_decomposer.py` (17 tests, 1 gated).
- Docs: this file; updated NODES, PROMPTS, TESTING, ARCHITECTURE, ROADMAP, CLAUDE.md, README.

## Verification log

| Check | Result |
|---|---|
| fast suite | 78 tests OK (4 skipped: LLM) |
| `python scripts/run_task_decomposer.py` (real model) | exit 0 in ~30 s; 8 ordered tasks, slug `block-dodger`, passes `check_plan`; descriptions specific to Block Dodger (blocks, 60 s timer, `spawnBlockOverPlayer`) |
| stability: Block Dodger + planner-generated snake, pong, circle clicker | 4/4 valid on the first call (no repair), 25–29 s each, game-specific hooks/scenes |
| no-write check | project file hashes identical before/after (fake and real runs) |
| `RUN_OLLAMA_TESTS=1` full suite | 78 tests OK in ~109 s; smoke_graph sha256 = baseline |

## Issues / follow-ups

- Every generated plan has the same 8-task skeleton, and one `code` task (T4) holds all three scene files. For the coder (M8, 14b model) that may be too much per call — revisit there (e.g. one scene per task via a decomposer rule).
- `test_writer`, `coder`, `fixer` prompt examples still use Block Dodger-like content; switch them when those nodes are built (M8, M11, M15).
