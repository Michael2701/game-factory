# M01 — Agent System Project Skeleton

Status: complete (2026-10-11) — awaiting user review

## Scope

- Base directory structure for the agent system.
- Documentation: README, CLAUDE.md (docs index), docs/{ROADMAP, ARCHITECTURE, SAFETY, TESTING, WORKFLOW}.md.
- Git baseline (`git init`, `.gitignore`).
- Test suite (stdlib `unittest`).
- `agents/smoke_graph.py` stays unchanged.

## Done criteria

- `source .venv/bin/activate && python agents/smoke_graph.py` succeeds.
- Required directories exist; docs present and cross-linked; full test suite green.

## Changes

- New dirs: `agents/{nodes,schemas,tools,prompts}/`, `games/`, `templates/`, `scripts/`, `docs/milestones/`, `tests/`.
- `__init__.py` in `agents`, `agents/nodes`, `agents/schemas`, `agents/tools`; `.gitkeep` in `agents/prompts`, `games`, `templates`, `scripts`.
- Docs: `CLAUDE.md`, `README.md`, `docs/{ROADMAP,ARCHITECTURE,SAFETY,TESTING,WORKFLOW}.md`, this file.
- Tests: `tests/test_m01_structure.py`, `tests/test_docs.py`, `tests/test_smoke_graph.py`.
- Git: `git init`, `.gitignore` (`.venv/ __pycache__/ *.pyc node_modules/ .DS_Store .idea/ .lavish/`). No commit yet.
- `agents/smoke_graph.py`: unchanged.

## Verification log

| Command | Result |
|---|---|
| `python agents/smoke_graph.py` | exit 0 in ~66 s (cold model load); printed `=== SPEC ===` (Block Dodger spec) and `=== REVIEW ===` |
| `python -m unittest discover -s tests -v` | 10 tests, OK (1 skipped: smoke) |
| `RUN_OLLAMA_TESTS=1 python -m unittest discover -s tests -v` | 10 tests, OK in ~50 s |
| `shasum -a 256 agents/smoke_graph.py` | `e0ff1d10…6b76` = baseline |
| Link-parser negative check | broken link `docs/NOPE.md` detected; URLs and `#anchors` ignored |

## Issues / follow-ups

- Ollama server was not running at start; started with `ollama serve` for verification. LLM tests need it running.
- No initial git commit yet — waiting for user approval.
- `pytest` intentionally not installed; stdlib `unittest` is enough for now.
