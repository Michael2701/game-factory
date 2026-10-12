# Roadmap

Source: [plan.md](../plan.md). Milestones are implemented **strictly in order**. After each one: verify, report, stop, and wait for explicit permission before starting the next.

## Status

| # | Milestone | Status |
|---|---|---|
| 1 | Agent System Project Skeleton | complete |
| 2 | Core Schemas | complete |
| 3 | Prompt Templates | complete |
| 4 | Planner Node | complete |
| 5 | Task Decomposer Node | complete |
| 6 | Safe Tool Layer | complete |
| 7 | Graph Skeleton | complete |
| 8 | Coder Node Dry Run | complete |
| 9 | File Change Applier | complete |
| 10 | Minimal Target Project Generator | complete |
| 11 | Test Writer Node Dry Run | complete |
| 12 | Command Runner Node | complete |
| 13 | End-to-End Dry Run Graph | complete |
| 14 | Approved Apply Flow | complete |
| 15 | Fixer Node | complete |
| 16 | Fix Loop Graph | complete |
| 17 | Reviewer Node | complete |
| 18 | Human Approval Gate | complete |
| 19 | Phaser Template as Agent Output Target | complete |
| 20 | First Real Generated Game Validation | complete (partial result: gate reached, no all-green run) — awaiting user review |

## Long-term pipeline

```
User game idea → Planner → Structured GameSpec → Task decomposition → Coder → Safe file tools
→ Test writer → Test runner → Fixer (if tests fail) → Reviewer → Human approval → Build artifact
→ (optional) portal / publishing
```

---

## Milestone 1 — Agent System Project Skeleton

**Objective:** base project structure and documentation.

- Keep `agents/smoke_graph.py` unchanged.
- Create `agents/{nodes,schemas,tools,prompts}/`, `games/`, `templates/`, `scripts/`, `docs/`, `tests/`.
- `README.md` (purpose, not building a game yet, goal, stack, status, setup, venv, smoke run, roadmap summary, safety).
- `docs/ROADMAP.md` (this file).

**Done when:** `source .venv/bin/activate && python agents/smoke_graph.py` works and the structure is in place.

## Milestone 2 — Core Schemas

**Objective:** Pydantic schemas for the agent system.

- Files: `agents/schemas/{game_spec,task_plan,test_result,review_result,agent_state}.py`.
- Concepts: `GameIdea`, `GameSpec`, `ImplementationTask`, `TaskPlan`, `FileChange`, `CommandResult`, `TestResult`, `ReviewResult`, `GameFactoryState`.
- `GameSpec`: title, slug, genre, engine, core_loop, scenes, controls, win_condition, lose_condition, test_requirements, asset_requirements, sound_requirements.
- `GameFactoryState`: user_idea, game_spec, task_plan, changed_files, command_results, test_result, review_result, fix_attempts, status.

**Done when:** a small script instantiates and validates all schemas with sample data.

## Milestone 3 — Prompt Templates

**Objective:** controlled prompts for each agent role.

- `agents/prompts/{planner,task_decomposer,coder,test_writer,fixer,reviewer}.md`.
- Emphasize structured output, small scope, testability, safety.
- Planner → GameSpec; decomposer → ordered TaskPlan; coder → one task, allowed files only; test writer → deterministic Playwright tests + hooks; fixer → only the failing issue; reviewer → structured feedback.

**Done when:** prompt files exist and are clear enough to be used by nodes.

## Milestone 4 — Planner Node

**Objective:** first real node, `planner_node` (`agents/nodes/planner.py`).

- Input: short idea. Output: validated `GameSpec`.
- `ChatOllama(model="qwen2.5-coder:14b", temperature=0.2)`; Pydantic validation; one JSON repair attempt; otherwise a structured error.
- Runner: `scripts/run_planner.py`.

**Done when:** `python scripts/run_planner.py "A simple game where the player dodges falling blocks for 60 seconds."` prints a valid GameSpec.

## Milestone 5 — Task Decomposer Node

**Objective:** `task_decomposer_node` (`agents/nodes/task_decomposer.py`).

- Input: `GameSpec`. Output: validated ordered `TaskPlan` (project structure, package.json, Vite entry, Phaser scenes, test hooks, Playwright tests, build, tests).
- Does **not** write files. Runner: `scripts/run_task_decomposer.py`.

**Done when:** a sample GameSpec yields a valid ordered TaskPlan.

## Milestone 6 — Safe Tool Layer

**Objective:** safe file and command tools.

- `agents/tools/{filesystem,commands,safety}.py` with `read_file`, `write_file`, `list_files`, `ensure_inside_project`, `run_command`.
- Only paths inside the project; reject outside paths and `~/.ssh`; command allowlist (`npm install`, `npm run build`, `npx playwright test`, project python scripts, safe listing); reject `rm -rf`, `sudo`, `curl | sh`, outside writes, secrets, global configs. Return stdout/stderr/exit code.
- `scripts/test_safe_tools.py`.

**Done when:** tests prove valid paths work, outside paths are rejected, safe commands work, dangerous commands are rejected.

## Milestone 7 — Graph Skeleton

**Objective:** `agents/game_factory_graph.py`: START → planner → task_decomposer → END.

- Output: `GameFactoryState` with GameSpec + TaskPlan. No file writing, no game, no tests.

**Done when:** `python agents/game_factory_graph.py` prints parsed GameSpec, TaskPlan, and final status.

## Milestone 8 — Coder Node Dry Run

**Objective:** `agents/nodes/coder.py` proposes `FileChange` objects (path, operation, content/patch, reason) for one `ImplementationTask`; never writes files.

- Runner: `scripts/run_coder_dry_run.py`.

**Done when:** a sample task yields valid FileChanges and the filesystem is provably unchanged.

## Milestone 9 — File Change Applier

**Objective:** `agents/tools/apply_changes.py` applies approved FileChanges.

- Validate paths; only `games/`, `templates/`, `generated/`; summary before applying; `dry_run=True` / `apply=True`; return changed files.

**Done when:** a test script creates a FileChange, shows dry-run, applies to a safe folder, and rejects unsafe paths.

## Milestone 10 — Minimal Target Project Generator

**Objective:** generate `generated/sample-game/` (package.json, index.html, src/main.ts — plain Vite TS placeholder) from FileChanges.

**Done when:** the tooling generates it and `npm install` + `npm run build` succeed.

## Milestone 11 — Test Writer Node Dry Run

**Objective:** `agents/nodes/test_writer.py` proposes Playwright tests as FileChanges; prefers `window.__GAME_STATE__` / `window.__TEST_API__` hooks.

**Done when:** it proposes a valid `tests/game.spec.ts` FileChange.

## Milestone 12 — Command Runner Node

**Objective:** `agents/nodes/test_runner.py` runs `npm install`, `npm run build`, `npx playwright test` via safe tools; returns `TestResult`.

**Done when:** it builds `generated/sample-game/` and returns structured CommandResult/TestResult.

## Milestone 13 — End-to-End Dry Run Graph

**Objective:** START → planner → task_decomposer → coder_dry_run → test_writer_dry_run → END.

- Output state: GameSpec, TaskPlan, proposed file changes, proposed test changes. No writes.

**Done when:** a user idea produces a complete dry-run plan.

## Milestone 14 — Approved Apply Flow

**Objective:** `--apply` flag on `agents/game_factory_graph.py`.

- Without `--apply`: dry run. With `--apply`: validate and write only inside `generated/` or `games/`.

**Done when:** both modes behave as described.

## Milestone 15 — Fixer Node

**Objective:** `fixer_node`: TestResult + relevant files + GameSpec + TaskPlan → minimal FileChanges.

- Minimal changes, no rewrites, no unrelated files, respect `max_fix_attempts`.

**Done when:** a synthetic failing TestResult yields a plausible minimal fix.

## Milestone 16 — Fix Loop Graph

**Objective:** planner → decomposer → coder → apply → test_runner → (failed and fix_attempts < 5 ? fixer → apply → test_runner : stop).

**Done when:** a deliberately broken generated project is fixed through the loop at least once.

## Milestone 17 — Reviewer Node

**Objective:** `reviewer_node`: GameSpec + files summary + TestResult → `ReviewResult` (scope, testability, hooks, suitability, UX, file organization).

**Done when:** it returns a structured ReviewResult.

## Milestone 18 — Human Approval Gate

**Objective:** states `tests_passed`, `needs_human_review`, `approved`, `rejected`, `needs_changes`; print next possible actions.

**Done when:** the graph reaches a human review state and stops.

## Milestone 19 — Phaser Template as Agent Output Target

**Objective:** `templates/phaser-vite-template/` (package.json, index.html, src/main.ts, src/scenes/, playwright.config.ts, tests/) — minimal, testable, used by agents as a target, not a hand-built game.

**Done when:** the agent system can use the template as a target.

## Milestone 20 — First Real Generated Game Validation

**Objective:** generate Block Dodger through the agent pipeline.

**Done when:** the system generates a playable browser game, runs build/tests, fixes simple errors, and reaches human review.
