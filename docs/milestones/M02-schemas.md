# M02 — Core Schemas

Status: complete (2026-10-11) — awaiting user review

## Scope

- Pydantic v2 models for the whole agent system (reference: [SCHEMAS.md](../SCHEMAS.md)).
- Block Dodger sample data for every model.
- Validation script + deterministic tests (no LLM).

## Done criteria

- `python scripts/validate_schemas.py` instantiates and validates all schemas with sample data (exit 0).
- Full test suite green.

## Changes

- New: `agents/schemas/{game_spec,task_plan,test_result,review_result,agent_state,examples}.py`; `agents/schemas/__init__.py` now re-exports all models.
- New: `scripts/validate_schemas.py` (removed the now-redundant `scripts/.gitkeep` placeholder from M1).
- New: `tests/test_schemas.py` (22 tests).
- Docs: new `docs/SCHEMAS.md`, this file; updated `CLAUDE.md`, `README.md`, `docs/{ROADMAP,ARCHITECTURE,TESTING}.md`.
- Design choices: `extra="forbid"` everywhere; `TaskPlan` dependencies only on earlier tasks; `FileChange` basic relative-path check (real guard in M6); `FileChange` lives in `task_plan.py` (plan.md lists 5 files).

## Verification log

| Command | Result |
|---|---|
| `python scripts/validate_schemas.py` | 8 models printed, "all schemas valid (8 models, JSON round-trip ok)", exit 0 |
| `python -m unittest discover -s tests -v` | 32 tests OK (1 skipped: smoke) |
| `RUN_OLLAMA_TESTS=1 python -m unittest discover -s tests -v` | 32 tests OK in ~64 s (incl. real smoke run) |
| `shasum -a 256 agents/smoke_graph.py` | `e0ff1d10…6b76` = baseline |

## Issues / follow-ups

- `langsmith` emits a `DeprecationWarning` (`asyncio.iscoroutinefunction`) on Python 3.14 — third-party, harmless.
- `graph.invoke()` returns a dict, not a `GameFactoryState`; rebuild with `model_validate` when needed (documented in SCHEMAS.md).
