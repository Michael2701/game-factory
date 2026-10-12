# Architecture

Status legend: **exists** = implemented, *planned (Mx)* = arrives in milestone x.

## Target pipeline

```
user idea
  │
  ▼
planner ──► GameSpec ──► task_decomposer ──► TaskPlan
                                               │
                                               ▼
                            coder (one ImplementationTask at a time) ──► FileChange[]
                                               │
                                     apply_changes (safe, approved)
                                               │
                              test_writer ──► Playwright tests (FileChange[])
                                               │
                                     test_runner ──► CommandResult[] / TestResult
                                               │
                         failed & fix_attempts < 5 ? ──► fixer ──► FileChange[] ─┐
                                               │                                 │
                                               │◄────────────── re-test ◄────────┘
                                               ▼
                                     reviewer ──► ReviewResult
                                               ▼
                                     human approval gate ──► build artifact
```

Nodes are LangGraph nodes over a shared `GameFactoryState` (**exists**, see [SCHEMAS.md](SCHEMAS.md)). LLM: `ChatOllama(model="qwen2.5-coder:14b", temperature=0.2)`. Every LLM output is parsed into a Pydantic model — free text is never a final output.

## Graph (current wiring, M13 dry run + M14 `--apply` + M16 `--fix-loop` + M17 reviewer + M18 human gate)

`agents/game_factory_graph.py`:

```
START → planner → task_decomposer → coder_dry_run → test_writer_dry_run → END
           └──────────┴──────────────┴──────────────────┴── status = error → END (partial proposals kept)
                                                                  └─(apply=True)→ apply_changes → END
                                                                  └─(fix_loop=True)→ apply_changes → test_runner ─┬─ passed / attempts used up → reviewer → human_gate → END (needs_human_review)
                                                                                                      ▲            ├─ error → END (no review)        reviewer error → END (no gate)
                                                                                                      │            │
                                                                                                      └ apply_fix ◄ fixer ◄┘ failed & fix_attempts < max_fix_attempts
                                                                                                        (fixer / apply_fix error → END)

build_fix_loop_graph:  START → test_runner → (same loop + reviewer + human_gate)        # project already on disk (scripts/run_fix_loop.py)
```

- `build_graph(llm=None, apply=False, root=PROJECT_ROOT)` compiles `StateGraph(GameFactoryState)` from `NODES` (or `APPLY_NODES` = `NODES` + `apply_changes` when `apply=True`; `root` lets tests write into a temp project); every LLM node gets the same `llm` via a lambda (tests pass `FakeLLM`); `_next_or_end(next)` routes errors to END.
- `run(idea, llm=None, apply=False, target_dir=None, root=PROJECT_ROOT) -> GameFactoryState`; `format_state(state, show_files)` → GAME SPEC / TASK PLAN / PROPOSED FILES / PROPOSED TESTS / APPLIED (if any) / STATUS; `main(argv, llm=None, root=PROJECT_ROOT)` is the CLI (`--show-files`, `--json`, `--apply`, `--target-dir`).
- **Dry run (default):** nothing is written; proposals live in `state.proposed_changes` / `state.proposed_test_changes`; the CLI prints a filesystem-unchanged proof (sha256 of all project files before/after) and the `--apply` hint; exit 0 only for `changes_proposed`.
- **`--apply` (M14):** the `apply_changes` node (`agents/nodes/applier.py`) merges all proposals into the final project and writes it into a **new or empty** folder below `generated/` or `games/` (default `generated/<slug>`, override `--target-dir`; never overwrites, never `templates/`). An explicit `--target-dir` is checked before any LLM call. The CLI prints an APPLY CHECK: files changed inside / outside the target (from the before/after hash diff). Exit 0 = `changes_applied` + nothing outside the target + diff == `changed_files`; 2 = target refused; 1 = anything else. Install/build/tests are **not** run with plain `--apply`.
- **`--fix-loop` (M16, implies `--apply`):** after `apply_changes`, `test_runner` runs install → build → Playwright on `state.target_dir`. `failed` with attempts left → `fixer` (proposes `fix_changes`, read-only) → `apply_fix` (`agents/nodes/applier.py`: preview → all-or-nothing write inside the existing `target_dir`, only below `generated/`/`games/`) → `test_runner` again. Stops on `passed` (`tests_passed`), `error`, a fixer/apply_fix error, or `fix_attempts == max_fix_attempts` (`tests_failed`). `--max-fix-attempts N` (0–20, default 5). Each step is recorded in `state.loop_history` (`LoopStep`: step, attempt, status, summary, files) by thin wrappers in the graph module (`_test_step`, `_fix_step`, `_apply_fix_step`), printed as `=== FIX LOOP ===` by `format_loop`. `recursion_limit(max_fix_attempts)` is passed to `invoke` so the LangGraph step budget always covers the loop. Exit 0 only when the run stops at the human gate with passing tests (`gate_passed`) and nothing changed outside the target (the gate's `.factory/state.json` is inside it). No rollback: a fix that breaks something else costs the next attempt.
- **Review (M17):** when the loop ends with `tests_passed` or `tests_failed` (attempts used up), `reviewer` (`agents/nodes/reviewer.py`) reads `target_dir` read-only and sets `state.review_result` (`ReviewResult`: verdict approve / needs_changes / reject + 6 checks). It **keeps `status`** (the human gate sets it next, M18); a reviewer NodeError sets `error`. A test-runner `error` ends the graph without review. `format_review` prints `=== REVIEW ===`.
- **Human gate (M18):** after a successful review, `human_gate` (`agents/nodes/human_gate.py`, deterministic) sets status `needs_human_review`, saves the whole state to `<target_dir>/.factory/state.json` (safe tools; `.factory/` is in `PROJECT_SKIP`, so no node reads it as source) and the graph ends. This is a stop + state file, **not** LangGraph `interrupt()`: there is no persistent checkpointer between processes. A human decides later with `scripts/decide.py --project-dir <dir> approve | reject | changes [--note …]` (`decide`: only from `needs_human_review` → `approved` / `rejected` / `needs_changes`; approve needs passing tests; one decision per gate; recorded as `state.human_decision`). `next_actions(state)` lists what to do next per status and is printed as `=== HUMAN REVIEW ===` (`format_gate`) by the CLI, `run_fix_loop.py` and `decide.py`. `needs_changes` triggers nothing automatically; re-running the fix loop on the project ends at the gate again (new state file). `format_loop` reads the loop outcome from `test_result`, not `status`.
- `build_fix_loop_graph(llm, root)` / `run_fix_loop(state, llm, root)`: the same loop starting at `test_runner` for a project already on disk (needs `target_dir` + `game_spec`). Used by `scripts/run_fix_loop.py` (broken fixtures or an existing `--project-dir`).
- **Template (M19):** `run()` sets `state.template = "phaser-vite-template"`. The decomposer plans on top of it, the coder/test writer start their virtual file system from `project_base(...)` (instantiated template), locked config files (package.json, index.html, tsconfig.json, playwright.config.ts) cannot be planned or changed, and `final_changes` writes template + proposals. See [GENERATORS.md](GENERATORS.md).
- **Cross-task coherence** (see [NODES.md](NODES.md)): virtual file system across coder tasks, integration files (`src/main.ts`) updatable by later tasks, `tests` tasks owned by the test writer, hook contract enforced on both sides.
- Importing the module has no side effects.
- **Adding a node later:** write it per [NODES.md](NODES.md), `add_node` with the llm lambda, route errors to END with a conditional edge like `_after_planner`, extend `format_state`, and add graph tests (structure + happy path + failure skips the rest).

## Core principles

- **Structured I/O**: nodes exchange Pydantic objects (GameSpec, TaskPlan, FileChange, TestResult, ReviewResult).
- **Propose, then apply**: LLM nodes only *propose* FileChanges; a separate deterministic applier writes them after validation/approval.
- **Constrained tools**: all filesystem/command access goes through `agents/tools/` (path guard + command allowlist).
- **Bounded loops**: fix loop capped (`fix_attempts < max_fix_attempts`, default 5) and the LangGraph recursion limit is derived from it.
- **Human in the loop**: graph stops at a human review state before anything is considered done.

## Directory map

| Path | Holds | Status |
|---|---|---|
| `agents/smoke_graph.py` | Original 2-node smoke test (planner → reviewer). Frozen. Runs on import — never import it. | exists |
| `agents/schemas/` | Pydantic models: game_spec, task_plan, test_result, review_result, agent_state; `examples.py` = Block Dodger samples | exists (M2) |
| `agents/prompts/` | Markdown prompt templates per role + strict `{{var}}` loader ([PROMPTS.md](PROMPTS.md)) | exists (M3) |
| `agents/llm.py` | `make_llm()` (qwen2.5-coder:14b), `extract_json` (+ `fix_invalid_escapes`), `parse_model`, `invoke_structured` (parse → check → repair → NodeError) — shared by LLM nodes | exists (M4–M5) |
| `agents/nodes/` | LangGraph nodes ([NODES.md](NODES.md)): planner (M4), task_decomposer (M5), coder (M8/M13), test_writer (M11/M13), applier (M14), test_runner (M12, deterministic), fixer (M15) and apply_fix (M16, fix loop), reviewer (M17, after the fix loop) and human_gate (M18, stops the graph) are in the graph | exists |
| `agents/fixtures/` | In-memory fixtures: `broken_projects.py` = a complete passing Phaser + Vite + Playwright project (`BASE_FILES`) and broken variants with their failing TestResults: fixer dry run (M15) and fix loop (M16; `fails_for_real` marks the cases that really fail on disk) | exists (M15) |
| `agents/tools/` | safety, filesystem, commands (M6), apply_changes (M9) — see [TOOLS.md](TOOLS.md) | exists |
| `agents/game_factory_graph.py` | Main graph + CLI (see Graph section; `--apply` since M14) | exists (M7, M13, M14) |
| `agents/generators/` | Deterministic target-project generators (`minimal_project.py`, M10) — [GENERATORS.md](GENERATORS.md) | exists (M10) |
| `scripts/` | Runners and manual check scripts: `validate_schemas.py` (M2), `run_planner.py` (M4), `run_task_decomposer.py` (M5), `test_safe_tools.py` (M6), `run_coder_dry_run.py` (M8), `test_apply_changes.py` (M9), `generate_sample_game.py` (M10), `run_test_writer_dry_run.py` (M11), `run_test_runner.py` (M12), `run_fixer_dry_run.py` (M15), `run_fix_loop.py` (M16), `run_reviewer.py` (M17), `decide.py` (M18), `new_from_template.py` (M19) | exists |
| `templates/` | Target project templates (phaser-vite-template) | *planned M19* |
| `generated/` | Agent-generated projects (`sample-game` from M10) — allowed write target; `node_modules/`, `dist/` git-ignored | exists (M10) |
| `games/` | Finished/approved games — allowed write target | *planned* |
| `tests/` | `unittest` test suite for the agent system | exists |
| `docs/` | Documentation (indexed from CLAUDE.md) | exists |

Python packages: `agents`, `agents.nodes`, `agents.schemas`, `agents.tools`, `agents.prompts`, `agents.generators` have `__init__.py`; run scripts and tests from the project root so `import agents...` resolves.

## State (`GameFactoryState`)

`user_idea → game_spec → task_plan → changed_files → command_results → test_result → review_result`, plus `fix_attempts`, `max_fix_attempts`, `status` (`FactoryStatus`) and `error`. Full field reference and status flow: [SCHEMAS.md](SCHEMAS.md).
