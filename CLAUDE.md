# CLAUDE.md — Game Factory documentation index

Local LangGraph + Ollama **agent system** that turns a short game idea into a tested browser game project.
The product is the agent system; games (e.g. Block Dodger) are only validation outputs.

## Current status

- **Done:** M1 Skeleton · M2 Schemas · M3 Prompts · M4 Planner · M5 Task Decomposer · M6 Safe Tools · M7 Graph Skeleton · M8 Coder Dry Run · M9 Applier · M10 Minimal Project · M11 Test Writer · M12 Test Runner · M13 End-to-End Dry Run · M14 Apply Flow · M15 Fixer Node · M16 Fix Loop Graph · M17 Reviewer Node · M18 Human Approval Gate · M19 Phaser Template
- **Roadmap M1–M20 done.** After the roadmap: **M21 — Playable generated game — complete**; **M21b — Quality bar, run log, fix-loop hardening — complete (infrastructure; runs partial)**; **M21c — Game-agnostic factory (per-game playtest) — in progress**.
- **Next:** [plan-2.md](plan-2.md) M22–M36 (backend, Studio, assets, public portal) — one milestone at a time, each with its own Lavish plan, only on the user's word.
- **Model:** set in the git-ignored `.env` (`GAME_FACTORY_MODEL`, see `.env.example`); default `qwen3:30b-a3b` (the qwen2.5-coder models were removed).
- **Git:** pushed to https://github.com/Michael2701/game-factory (`main`, like Agentic_SRE_Testbed); `generated/` is git-ignored (run outputs). Commit/push only when the user says so.

## Hard rules (always apply)

1. **Milestone gate** — one milestone at a time, in order. Finish → verify → report → STOP. Next milestone only when the user says so. → [docs/WORKFLOW.md](docs/WORKFLOW.md)
2. **Safety** — work only inside this project; no destructive commands; `agents/smoke_graph.py` is frozen. → [docs/SAFETY.md](docs/SAFETY.md)
3. **Test everything** — every milestone adds tests and runs them (plus the smoke run) before reporting. → [docs/TESTING.md](docs/TESTING.md)
4. **Plans** go to a Lavish page with an Approve button before implementation (global user rule).
5. **Keep this index current** — new doc → add a row below; milestone done → update "Current status" and [docs/ROADMAP.md](docs/ROADMAP.md).

## Documentation index

| Document | Read when |
|---|---|
| [README.md](README.md) | Setup, venv, how to run things (human-facing overview) |
| [plan.md](plan.md) | Original brief from the user — source of truth for milestone scope |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Choosing/scoping a milestone; checking milestone status |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Deciding where code goes; target pipeline; **current graph wiring** (Graph section) |
| [docs/GENERATORS.md](docs/GENERATORS.md) | Target project format, deterministic generators, **Phaser template (M19): files, locks, API**, npm version pins |
| [docs/NODES.md](docs/NODES.md) | Writing or changing an agent node (shape, llm injection, parse → repair → NodeError, fake-LLM tests) |
| [docs/PROMPTS.md](docs/PROMPTS.md) | Using or changing agent prompts; loader API; known LLM quirks |
| [docs/SCHEMAS.md](docs/SCHEMAS.md) | Using or changing Pydantic models (GameSpec, TaskPlan, FileChange, GameFactoryState, …); sample data |
| [docs/SAFETY.md](docs/SAFETY.md) | Before touching files, running commands, or building agent tools |
| [docs/TOOLS.md](docs/TOOLS.md) | Agent file/command access: path guard, protected paths, write roots, command allowlist, **applying FileChanges** |
| [docs/TESTING.md](docs/TESTING.md) | Writing or running tests; verifying a milestone |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | Starting/finishing a milestone; writing the milestone report |
| [docs/milestones/M01-skeleton.md](docs/milestones/M01-skeleton.md) | M1 scope, done criteria, verification log |
| [docs/milestones/M02-schemas.md](docs/milestones/M02-schemas.md) | M2 scope, done criteria, verification log |
| [docs/milestones/M03-prompts.md](docs/milestones/M03-prompts.md) | M3 scope, done criteria, verification log |
| [docs/milestones/M04-planner.md](docs/milestones/M04-planner.md) | M4 scope, done criteria, verification log |
| [docs/milestones/M05-task-decomposer.md](docs/milestones/M05-task-decomposer.md) | M5 scope, done criteria, verification log |
| [docs/milestones/M06-safe-tools.md](docs/milestones/M06-safe-tools.md) | M6 scope, done criteria, verification log |
| [docs/milestones/M07-graph-skeleton.md](docs/milestones/M07-graph-skeleton.md) | M7 scope, done criteria, verification log |
| [docs/milestones/M08-coder-dry-run.md](docs/milestones/M08-coder-dry-run.md) | M8 scope, verification log, **review of generated code + cross-task coherence findings** |
| [docs/milestones/M09-applier.md](docs/milestones/M09-applier.md) | M9 scope, done criteria, verification log |
| [docs/milestones/M10-minimal-project.md](docs/milestones/M10-minimal-project.md) | M10 scope, done criteria, verification log |
| [docs/milestones/M11-test-writer.md](docs/milestones/M11-test-writer.md) | M11 scope, verification log, **real-model test review + prompt tuning** |
| [docs/milestones/M12-test-runner.md](docs/milestones/M12-test-runner.md) | M12 scope, verification log, **Playwright 1.62.0 ↔ cached Chromium finding** |
| [docs/milestones/M13-e2e-dry-run.md](docs/milestones/M13-e2e-dry-run.md) | M13 scope, **cross-task coherence fixes + before/after review** |
| [docs/milestones/M14-apply-flow.md](docs/milestones/M14-apply-flow.md) | M14 scope, verification log, **first applied project build result (Phaser import / version findings)** |
| [docs/milestones/M15-fixer.md](docs/milestones/M15-fixer.md) | M15 scope, verification log, **sample fixer input/output (synthetic + real block-dodger build error)** |
| [docs/milestones/M16-fix-loop.md](docs/milestones/M16-fix-loop.md) | M16 scope, verification log, **real loop runs (fixtures that really fail; block-dodger)**, finding: M15 cases pass on vite 8 / macOS |
| [docs/milestones/M17-reviewer.md](docs/milestones/M17-reviewer.md) | M17 scope, verification log, **real reviews (fixture, block-dodger, loop + review)**, finding: qwen copies the prompt example |
| [docs/milestones/M18-human-gate.md](docs/milestones/M18-human-gate.md) | M18 scope, verification log, **real loop stopping at the gate + decide.py**, why END + state file instead of `interrupt()` |
| [docs/milestones/M19-phaser-template.md](docs/milestones/M19-phaser-template.md) | M19 scope, template files, verification log, **real dry run on top of the template** |
| [docs/milestones/M21-playable-game.md](docs/milestones/M21-playable-game.md) | M21: acceptance spec with real input, browser-error fixture + source maps, fixer anti-repeat, model config, runs r7/r7b (14b) and r8 (32b, 11/11) |
| [docs/milestones/M20-first-generated-game.md](docs/milestones/M20-first-generated-game.md) | M20 runs r1–r6 (Block Dodger through the full pipeline), agent-system fixes per round, limitations, **next steps** |
| [docs/milestones/M21b-quality-bar.md](docs/milestones/M21b-quality-bar.md) | Quality bar, **run log** (logs/runs, show_run.py), model `.env` + limits, revert by acceptance progress, deterministic Phaser checks, runs r10–r13 |
| [docs/milestones/M21c-game-agnostic.md](docs/milestones/M21c-game-agnostic.md) | **GameSpec.playtest → per-game acceptance + hook contract**, generic template hooks, fixture games (clicker, jumper), runs on 3 different ideas |
| [plan-2.md](plan-2.md) | Next roadmap M22–M36: backend, Studio, asset management, public portal (from the user) |

## Quick commands

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v                      # fast tests (no LLM)
RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1 caffeinate -i python -m unittest discover -s tests -v   # + LLM (needs `ollama serve`) + npm (network) tests
python agents/smoke_graph.py                                 # LangGraph + Ollama smoke run
python scripts/validate_schemas.py                           # build + validate all schema samples
python scripts/run_planner.py "<game idea>"                    # planner node → GameSpec JSON (needs Ollama)
python scripts/run_task_decomposer.py [--spec spec.json]      # decomposer node → TaskPlan JSON (needs Ollama)
python scripts/test_safe_tools.py                            # safe tool layer PASS/FAIL table
python scripts/test_apply_changes.py                         # applier PASS/FAIL table (sandbox)
python scripts/generate_sample_game.py [--dry-run]           # generated/sample-game: files + npm install + build (network)
python agents/game_factory_graph.py ["idea"] [--show-files] [--json]  # e2e dry run: spec → plan → proposed code + tests, no writes (~4 min, Ollama)
python agents/game_factory_graph.py ["idea"] --apply [--target-dir generated/x]  # + write to generated/<slug> (new/empty folder only)
python scripts/run_coder_dry_run.py [--task T4]              # coder dry run → proposed FileChanges, no writes (needs Ollama)
python scripts/run_test_writer_dry_run.py [--project-dir generated/x]  # test writer dry run → proposed tests (needs Ollama)
python scripts/run_test_runner.py [--project-dir generated/x] # install + build + playwright → TestResult
python scripts/run_fixer_dry_run.py [--case missing-file|win-logic|...] [--project-dir generated/x]  # failing result → proposed minimal fix (diff), no writes (Ollama)
python agents/game_factory_graph.py ["idea"] --fix-loop [--max-fix-attempts 5]  # apply, then test → fix → re-test → review → stop at the human gate (Ollama + npm)
python scripts/run_fix_loop.py [--case two-bugs] [--project-dir generated/x]  # fix loop (+ review + human gate) on a broken fixture (→ generated/fix-demo-<case>) or existing project
python scripts/run_reviewer.py --project-dir generated/x [--spec spec.json] [--json]  # test + review an existing project → ReviewResult, no writes (Ollama + npm)
python scripts/new_from_template.py --target generated/x [--check]  # Phaser template → new project (+ install, build, 3 smoke tests)
python scripts/audit_generated.py --project-dir generated/x   # M21: sources match the agent-write manifest (no manual edits)
GAME_FACTORY_MODEL=qwen3:30b-a3b python agents/game_factory_graph.py --fix-loop   # or --model …, or .env
python agents/game_factory_graph.py "idea" --fix-loop --run-id my-run   # live log: logs/runs/my-run/run.log
python scripts/show_run.py latest [--follow] [--llm N]          # run timeline / one LLM call (prompt, reasoning, reply)
python scripts/decide.py --project-dir generated/x --show | approve | reject | changes [--note "…"]  # human decision at the gate (no LLM)
```
