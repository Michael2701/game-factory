# Game Factory

An **agentic system for creating browser games**, built locally with LangGraph and Ollama.

## What this project is

Game Factory is a pipeline of LLM agents (planner, task decomposer, coder, test writer, test runner, fixer, reviewer) that will take a short game idea and autonomously produce a small, tested browser game project.

**We are not manually building a game yet.** The agent system is the product. Games — such as *Block Dodger* (dodge falling blocks for 60 seconds) — are only target outputs, test fixtures, and validation examples.

## Project goal

Build a local LangGraph-based agent system that can take a short game idea and autonomously:

1. create a structured game spec,
2. break it into small implementation tasks,
3. write project files through safe, constrained tools,
4. write and run tests,
5. fix failures in a bounded loop,
6. review the result,
7. stop for human approval and prepare a build artifact.

## Tech stack

| Layer | Tools |
|---|---|
| Agent system | Python 3.14, LangGraph, LangChain, langchain-ollama, Pydantic |
| Local LLM | Ollama, `qwen2.5-coder:14b` |
| Generated games | TypeScript, Phaser, Vite |
| Game tests | Playwright |
| Tooling | Git, Node.js / npm |

## Current status

- **Milestone 1 — Project Skeleton:** complete.
- **Milestone 2 — Core Schemas:** complete.
- **Milestone 3 — Prompt Templates:** complete.
- **Milestone 4 — Planner Node:** complete.
- **Milestone 5 — Task Decomposer Node:** complete.
- **Milestone 6 — Safe Tool Layer:** complete.
- **Milestone 7 — Graph Skeleton:** complete.
- **Milestone 8 — Coder Node Dry Run:** complete.
- **Milestone 9 — File Change Applier:** complete.
- **Milestone 10 — Minimal Target Project Generator:** complete.
- **Milestone 11 — Test Writer Node Dry Run:** complete.
- **Milestone 12 — Command Runner Node:** complete.
- **Milestone 13 — End-to-End Dry Run Graph:** complete.
- **Milestone 14 — Approved Apply Flow:** complete.
- **Milestone 15 — Fixer Node:** complete.
- **Milestone 16 — Fix Loop Graph:** complete.
- **Milestone 17 — Reviewer Node:** complete.
- **Milestone 18 — Human Approval Gate:** complete.
- **Milestone 19 — Phaser Template as Agent Output Target:** complete.
- **Milestone 20 — First Real Generated Game Validation:** complete with a partial result.
- **M21 — Playable generated game (after the roadmap):** complete. An independent acceptance test (real click + arrow keys), browser-error capture with source maps, fixer anti-repeat, configurable model; qwen2.5-coder:32b generated a Block Dodger that passes 11/11 tests on the first try.
- **M22 — Quality bar:** in progress (see [docs/ROADMAP.md](docs/ROADMAP.md) for the live status).
- Existing: Python venv with LangGraph stack, `agents/smoke_graph.py` (a two-node LangGraph planner → reviewer smoke test against Ollama).
- Pydantic schemas in `agents/schemas/` ([docs/SCHEMAS.md](docs/SCHEMAS.md)); check them with `python scripts/validate_schemas.py`.
- Prompt templates for all agent roles in `agents/prompts/` ([docs/PROMPTS.md](docs/PROMPTS.md)).
- Planner node: `python scripts/run_planner.py "<game idea>"` prints a validated GameSpec ([docs/NODES.md](docs/NODES.md)).
- Task decomposer node: `python scripts/run_task_decomposer.py [--spec spec.json]` prints a validated TaskPlan.
- Safe tool layer for agents (`agents/tools/`, [docs/TOOLS.md](docs/TOOLS.md)); check with `python scripts/test_safe_tools.py`.
- Graph (dry run): `python agents/game_factory_graph.py ["idea"] [--show-files]` runs idea → GameSpec → TaskPlan → proposed code → proposed tests and proves that no file was written.
- Graph (apply): `python agents/game_factory_graph.py ["idea"] --apply [--target-dir generated/x]` additionally writes the proposed project into a new folder below `generated/` or `games/` (default `generated/<slug>`, never overwrites) and proves nothing outside it changed.
- Coder (dry run): `python scripts/run_coder_dry_run.py [--task T4]` proposes file changes for one task without writing anything.
- Applier: `agents/tools/apply_changes.py` validates proposed changes (dry run by default) and writes them only below games/, templates/, generated/; demo: `python scripts/test_apply_changes.py`.
- Target project generator: `python scripts/generate_sample_game.py` creates and builds `generated/sample-game` (Vite + TS placeholder) — [docs/GENERATORS.md](docs/GENERATORS.md).
- Test writer (dry run): `python scripts/run_test_writer_dry_run.py` proposes deterministic Playwright tests without writing anything.
- Test runner: `python scripts/run_test_runner.py [--project-dir generated/x]` runs install, build and Playwright tests and prints a structured TestResult.
- Fixer (dry run): `python scripts/run_fixer_dry_run.py [--case missing-file|win-logic|...] [--project-dir generated/x]` proposes a minimal fix for a failing build/test as a diff, without writing anything.
- Fix loop: `python agents/game_factory_graph.py ["idea"] --fix-loop [--max-fix-attempts 5]` applies the project, then tests → fixes → re-tests until the tests pass or the attempts run out. `python scripts/run_fix_loop.py [--case two-bugs] [--project-dir generated/x]` runs the same loop on a deliberately broken fixture (written to `generated/fix-demo-<case>`) or an existing project. Since M17 the loop ends with a review (`=== REVIEW ===`: verdict + 6 checks); since M18 it then stops at the human gate (`=== HUMAN REVIEW ===`, status `needs_human_review`, state saved to `<project>/.factory/state.json`).
- Review: `python scripts/run_reviewer.py --project-dir generated/x [--spec spec.json] [--json]` runs install/build/tests on an existing project, then the reviewer node → `ReviewResult` (writes nothing).
- Phaser template (M19): `templates/phaser-vite-template/` is the target format of every generated game (pinned Phaser 3.90 / Vite / Playwright, hook contract, 3 smoke tests; config files locked for the agents). `python scripts/new_from_template.py --target generated/x --check` creates a project from it and runs build + tests.
- Human approval: `python scripts/decide.py --project-dir generated/x --show | approve | reject | changes [--note "…"]` records the decision (`approved` / `rejected` / `needs_changes`) and prints the next possible actions. Approve needs passing tests; one decision per gate.

## Setup

Prerequisites: Python 3.14, [Ollama](https://ollama.com), Node.js + npm, Git.

```bash
# 1. Pull the local model (once)
ollama pull qwen2.5-coder:14b

# 2. Make sure the Ollama server is running
ollama serve            # or run the Ollama desktop app

# 3. (only if .venv is missing) create the venv and install deps
python3.14 -m venv .venv
.venv/bin/pip install langgraph langchain langchain-ollama pydantic
```

## Activate the venv

```bash
source .venv/bin/activate
# deactivate later with: deactivate
```

## Run agents/smoke_graph.py

```bash
source .venv/bin/activate
python agents/smoke_graph.py
```

It asks the local model to write a tiny game spec, then reviews it, and prints `=== SPEC ===` and `=== REVIEW ===` sections. Requires `ollama serve`.

## Run the tests

```bash
python -m unittest discover -s tests -v                      # fast, no LLM
RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1 python -m unittest discover -s tests -v   # + LLM tests (Ollama) and npm tests (network)
```

## Roadmap summary

Full details: [docs/ROADMAP.md](docs/ROADMAP.md).

1. Project skeleton · 2. Core schemas · 3. Prompt templates · 4. Planner node · 5. Task decomposer node · 6. Safe tool layer · 7. Graph skeleton · 8. Coder node (dry run) · 9. File change applier · 10. Minimal target project generator · 11. Test writer node (dry run) · 12. Command runner node · 13. End-to-end dry-run graph · 14. Approved apply flow · 15. Fixer node · 16. Fix loop graph · 17. Reviewer node · 18. Human approval gate · 19. Phaser template as output target · 20. First real generated game (Block Dodger)

Milestones are implemented strictly in order; each one is verified and approved before the next begins.

## Safety rules

Full details: [docs/SAFETY.md](docs/SAFETY.md).

- Work only inside this project directory.
- Never touch `~/.ssh`, global configs, credentials, or other repositories.
- No destructive commands (`rm -rf`, `sudo`, `curl | sh`, …); no deleting files unless explicitly asked.
- `agents/smoke_graph.py` is not modified unless explicitly asked.
- Agent tools are constrained: path checks + command allowlist; generated code is written only to allowed folders (`games/`, `templates/`, `generated/`).
