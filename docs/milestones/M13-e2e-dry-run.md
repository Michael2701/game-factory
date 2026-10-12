# M13 — End-to-End Dry Run Graph

Status: complete (2026-10-11)

## Scope

Graph START → planner → task_decomposer → coder_dry_run → test_writer_dry_run → END producing GameSpec, TaskPlan, proposed code and proposed tests without writing files — and fixing the cross-task coherence problems found in M8/M11.

## Done criteria

A user idea produces a complete dry-run plan for a game project.

## Changes

- State: `proposed_changes`, `proposed_test_changes`; new status `changes_proposed`.
- Coder (`agents/nodes/coder.py`): `merge_changes` (virtual file system), `optional_paths` (integration files such as `src/main.ts` may be **updated**, never created, not required), `HOOK_CONTRACT` check for `test_hooks` tasks, `coder_dry_run_node` (tasks in plan order, each sees all earlier proposals; `tests` tasks left to the test writer; stops at the first NodeError keeping partial proposals).
- Test writer: `test_writer_dry_run_node` (sees the merged virtual project); new check — every `__TEST_API__.x` / `__GAME_STATE__.x` used by the tests must exist in the project's hook files.
- Prompts: coder `{{optional_paths}}` + rules (fit existing files; do only your own task in integration files; hook contract for test_hooks tasks); test writer "use exactly the hooks defined in the project".
- Graph (`agents/game_factory_graph.py`): 4 nodes, error → END after each; `format_state` with PROPOSED FILES / PROPOSED TESTS; `--show-files`; filesystem-unchanged proof; exit 0 only for `changes_proposed`.
- Tests: `tests/test_graph.py` rewritten for the 4-node graph; new coder tests (optional paths, merge, hook contract) and test writer tests (hooks must exist).
- Docs: ARCHITECTURE, NODES, SCHEMAS, PROMPTS, TESTING, ROADMAP, CLAUDE.md, README, this file.

## Verification log

| Check | Result |
|---|---|
| fast suite | 223 tests OK (11 skipped) |
| real run 1 (`python agents/game_factory_graph.py --show-files`, Block Dodger) | exit 0, 3 min 31 s, `changes_proposed`, 8 proposed files + tests, filesystem unchanged, all .ts syntax ok. Coherence: scenes registered ✅ (T4 updated main.ts); but hooks duplicated (T4 wrote hooks into main.ts with a broken `this.game`, T5's `setupTestHooks` never called), `__GAME_STATE__.result` missing, tests used 2 undefined hooks (9/11) |
| fixes | coder: hook-contract check + "only your own task in integration files" rule; test writer: used hooks must be defined (both feed the repair prompt) |
| real run 2 | exit 0, 3 min 48 s, `changes_proposed`, filesystem unchanged, all .ts syntax ok. Coherence: scenes registered in T3, T5 created `setupTestHooks(game)` **and wired it in main.ts**, contract complete, **8/8 hooks used by the tests are defined**, package.json build = `vite build` |
| `RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1 caffeinate -i` full suite | 223 tests OK in ~373 s (incl. a third real e2e run via the gated graph test); smoke_graph sha256 = baseline |

## Remaining issues (for the build/test/fix loop, M14–M16)

- Code correctness, not coherence: `game.scene.getCurrentScene()` is not a Phaser 3 API; `GameScene`/`GameOverScene` used as types in testHooks.ts without imports (vite build does not type-check, so this may only surface at runtime or with `tsc`).
- The hook-definition check is lexical (a name appearing anywhere in a hooks file counts as defined) — good enough as a guard, not a proof.
- A full dry run takes ~3.5–4 min on qwen2.5-coder:14b (7 LLM calls, no repairs needed in run 2).
