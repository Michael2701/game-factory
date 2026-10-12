# M14 — Approved Apply Flow

Status: complete (2026-10-11)

## Scope

`--apply` flag on `agents/game_factory_graph.py`. Without it: dry run (M13 behaviour). With it: validate the proposed project and write it only inside `generated/` or `games/`.

## Done criteria

- `python agents/game_factory_graph.py "game idea"` does a dry run only.
- `python agents/game_factory_graph.py "game idea" --apply` writes files only inside the allowed `generated/` or `games/` folders.

## Changes

- State: `target_dir: str | None`; new status `changes_applied`.
- `agents/nodes/applier.py` (new, deterministic):
  - `final_changes(state)` merges code + test proposals (`merge_changes`) into one `create` per file. The coder's create → update chains (e.g. `src/main.ts` touched by T3, T4, T5) would otherwise be rejected by the applier (update of a missing file, duplicates).
  - `check_target(dir)` accepts only a new or empty folder below `generated/` or `games/` (not `templates/`, not a bare root, nothing outside the project or protected).
  - `apply_node(state, root)` checks the target (default `generated/<slug>`), validates everything with a dry-run `apply_changes`, then writes all or nothing. Invalid input (including a change that bypassed the schema) becomes `status=error` with 0 files written.
- Graph: `build_graph(llm, apply=False, root)` adds `apply_changes` after `test_writer_dry_run` only when `apply=True`; error → END as before. `run(..., apply, target_dir, root)`.
- CLI: `--apply`, `--target-dir` (needs `--apply`; checked **before** any LLM call). The `=== APPLIED → <dir> ===` section lists every written file.
  - Dry run prints the `--apply` hint.
  - Apply prints `=== APPLY CHECK ===`: files changed inside / outside the target, from a sha256 diff of the whole project before/after.
  - Exit codes: 0 = success (dry run: nothing changed; apply: `changes_applied`, nothing outside the target, diff == `changed_files`); 2 = target refused; 1 = otherwise.
- Tests: `tests/test_applier_node.py` (new, 10 tests); `tests/test_graph.py` + 10 apply-flow tests in a temp project root (the real `generated/` is never touched by the suite).
- Docs: ARCHITECTURE (Graph), NODES, SCHEMAS, TOOLS, TESTING, ROADMAP, README, CLAUDE.md, this file.

## Verification log

| Check | Result |
|---|---|
| fast suite | 243 tests OK (11 skipped) |
| `python scripts/validate_schemas.py` | all schemas valid |
| `python agents/smoke_graph.py` | ok |
| real dry run `python agents/game_factory_graph.py` | exit 0, 3 min 40 s, `changes_proposed`, `filesystem unchanged: yes (92 project files)`, hint `re-run with --apply to write the project to generated/block-dodger/` |
| real apply `python agents/game_factory_graph.py --apply` | exit 0, 3 min 59 s, `changes_applied`. Proposals: 10 changes (main.ts created by T3, updated by T4 and T5) → 8 files written to `generated/block-dodger/`. APPLY CHECK: 8 inside, **0 outside** |
| re-apply `--apply --target-dir generated/block-dodger` | exit 2 instantly: `target already exists and is not empty (nothing is overwritten)`; no LLM call |
| `--apply --target-dir templates/x` / `../outside` | exit 2: `target must be a folder below ['generated', 'games']` / `path is outside the project` |
| informative: `python scripts/run_test_runner.py --project-dir generated/block-dodger` | install ok (4 s); **build failed** — see below |
| `RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1` full suite | 243 tests; all npm and LLM tests pass **except** the gated real e2e dry run `test_graph.GraphLLMTest.test_done_when_command`, which failed (exit 1, graph status `error`, the failing node's raw output was the test writer's JSON). The 3000-char output tail the test keeps cut off the exact NodeError message, so the reason is **not verified**. An earlier full run also reported 1 failure (which test was not captured). This is the M13 dry-run path with the real model; the same command passed in both manual runs above. smoke_graph sha256 = baseline |

## First applied project — build result (input for M15/M16/M19)

`npm run build` fails: `'default' is not exported by node_modules/phaser/dist/phaser.esm.js, imported by src/scenes/StartScene.ts` (`import Phaser from 'phaser'`).

- The LLM chose loose, old version ranges: `phaser ^3.60.0` (resolved 3.90.0), `vite ^2.8.0` (resolved 2.9.18), `typescript ^4.5.0`, `@playwright/test ^1.18.0`. The last one does not match the cached Chromium (needs 1.62.0, see M12).
- Phaser 3.90's ESM build has no default export. Generated code should use `import * as Phaser from 'phaser'`, or the template should pin versions and an import style (M19).
- No `playwright.config.ts` was proposed (T6 lists it, but the test writer only produced `tests/game.spec.ts`).

These are exactly the failures the fixer loop (M15/M16) and the pinned Phaser template (M19) are meant to handle. They are not apply-flow problems.

## Issues / follow-ups

- **Real e2e dry run was flaky — two causes, both fixed.**
  - Diagnosis: the gated test now prints the node error without the raw output (`failure_summary` in `tests/test_graph.py`). 4 graph runs with saved `--json` states and one more gated run showed two test_writer failure modes.
  - 1) `Invalid JSON: invalid escape`: the model wrote TS code with `\'` (`'... the player\'s position ...'`) inside JSON strings, and repair repeated it. Fix: `agents/llm.py` `fix_invalid_escapes` (used by `extract_json`, i.e. by every LLM node) keeps the backslash of escapes JSON does not know, which yields the code the model meant. The captured failing output now parses and passes all test-writer checks.
  - 2) Tests used hooks the project does not define (`__GAME_STATE__.playerX/playerY/blockAt`), and repair could not fix that: it never sees the project files, and its prompt said "do not change the meaning". Fix: the check error now includes the hook files' content and says "change only the test code … keep this change's path and operation". The repair prompt allows changing content where an error lists what is available.
  - Real-model check (scripted bad first reply with `playerX`/`blockAt` + real qwen repair, project `generated/block-dodger`): before the wording fix 0/3 (repair switched `create` → `update`), after it 3/3 repaired using only defined hooks.
  - Tests: `tests/test_planner.py` (escapes), `tests/test_test_writer.py` (error carries the hooks).
  - After both fixes: `RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1` full suite **246 tests OK** (incl. the real e2e dry run), plus 3 extra real graph runs, all `changes_proposed` (exit 0). smoke_graph sha256 = baseline.

- `generated/block-dodger/` stays in the working tree (its `node_modules/` is git-ignored). Re-running `--apply` with the same slug is refused by design. Delete the folder manually or pass another `--target-dir`.
- The apply flow does not run install/build/tests; that is the fix loop (M16).
