# M16 — Fix Loop Graph

Status: complete (2026-10-11) — awaiting user review

## Scope

planner → decomposer → coder → apply → test_runner → (failed and fix_attempts < max ? fixer → apply fix → test_runner : stop). Controlled fixture for the Done-when.

## Done criteria

A deliberately broken generated project is fixed through the loop at least once. **Met:**
- `missing-file` and `win-logic` were each fixed in 1 round.
- `two-bugs` was fixed in 2 rounds.
- Every fix is a real rebuild plus real Playwright tests with qwen2.5-coder:14b, and nothing changed outside the project.

## Graph

```
… → test_writer_dry_run → apply_changes → test_runner ─┬─ passed → END (tests_passed)
                                              ▲         ├─ error → END
                                              │         ├─ failed, attempts left → fixer → apply_fix ─┘
                                              │         └─ failed, attempts used up → END (tests_failed)
fixer / apply_fix error → END
build_fix_loop_graph: START → test_runner → (same loop)
```

## Changes

- `agents/game_factory_graph.py`:
  - `build_graph(..., fix_loop=True)` and the CLI `--fix-loop` (implies `--apply`), `--max-fix-attempts N` (0–20, default 5).
  - `build_fix_loop_graph` / `run_fix_loop(state)` for a project already on disk.
  - `_after_test` routing.
  - Wrappers `_test_step` / `_fix_step` / `_apply_fix_step` record every step in `state.loop_history`.
  - `format_loop` prints `=== FIX LOOP ===`.
  - `recursion_limit(max_fix_attempts)` is passed to `invoke` (the LangGraph default of 25 would cap the loop at about 6 rounds).
  - Exit code with `--fix-loop`: 0 only for `tests_passed` and nothing outside the target.
- `agents/nodes/applier.py`:
  - `check_fix_target`: an existing folder below `generated/` or `games/`.
  - `apply_fix_node`: preview, then an all-or-nothing write of `state.fix_changes`; clears `fix_changes`, adds to `changed_files`, sets status `testing`; errors start with `apply_fix:`.
- `agents/nodes/test_runner.py`: the node tests `state.target_dir` when set.
- State: `LoopStep` (step, attempt, status, summary, files) and `GameFactoryState.loop_history`, plus a sample.
- `agents/fixtures/broken_projects.py`:
  - `BASE_FILES` is now a **complete passing project**: `playwright.config.ts` with a `vite preview` webServer on port 41730, test timeout 15 s, and a fix to the `startGame` hook (it now stops StartScene).
  - Verified for real: install, build, Playwright 3/3 in about 5 s.
  - New cases that **really fail**:
    - `missing-file`: `./scenes/PlayScene` does not exist, so the build fails;
    - `win-logic`: `timeLeft < 0` never wins, so a Playwright test fails at runtime;
    - `two-bugs`: both at once.
  - `fails_for_real` flag; `also_broken`.
- `agents/nodes/fixer.py` + `fixer.md` (hardening found by the gated run):
  - `playwright.config.ts` is relevant only when the failure names it;
  - `check_fix` rejects added timeout/wait lines in tests and the config;
  - prompt rule: a test timeout means the state was never reached.
- `scripts/run_fix_loop.py` (new):
  - `--case` writes the fixture into a NEW folder `generated/fix-demo-<case>` (an existing one gives exit 2 before anything runs);
  - `--project-dir` runs the loop on an existing project;
  - prints the loop, the source diff made by the loop, and the inside/outside proof.
- Tests:
  - `tests/test_fix_loop.py` (new; 25 fast, 2 gated). `FakeChecks` judges the project on disk, so fixer → apply_fix → re-test runs end to end without npm.
  - Gated: real fixtures behave as declared (npm), and the real loop fixes `two-bugs` (npm + Ollama).
  - `tests/test_fixer.py` adjusted for the config file and multi-bug cases.
- Docs: ARCHITECTURE (graph), NODES, SCHEMAS, TESTING, ROADMAP, README, CLAUDE.md, M15 (finding), this file.

## Real runs

`python scripts/run_fix_loop.py --case two-bugs` (exit 0, 52 s):

```
#0  test      failed   install ok · build failed (exit 1)
#1  fix       proposed Build failed: Could not resolve './scenes/PlayScene' in src/main.ts — …  [src/main.ts]
#1  apply_fix applied    [src/main.ts]
#1  test      failed   install ok · build ok · tests 2/3 passed
#2  fix       proposed Test timeout of 15000ms exceeded — the game should set result to 'win' when timeLeft is less than or equal to 0 …  [src/scenes/GameScene.ts]
#2  apply_fix applied    [src/scenes/GameScene.ts]
#2  test      passed   install ok · build ok · tests 3/3 passed
tests passed after 2 fix attempt(s)

-import { GameScene } from './scenes/PlayScene';
+import { GameScene } from './scenes/GameScene';
-    if (this.timeLeft < 0) {
+    if (this.timeLeft <= 0) {
files changed outside it: 0
```

| Run | Result |
|---|---|
| `--case missing-file` | exit 0 · 1 round · 1-line fix in main.ts · 21.9 s |
| `--case win-logic` | exit 0 · 1 round · `<` → `<=` in GameScene.ts (runtime bug found from the Playwright failure alone) · 40.6 s |
| `--case two-bugs` | exit 0 · 2 rounds (build error, then the hidden test failure) · 52.0 s |
| `--case phaser-default` | exit 0 · **0 rounds**: the project passes as written (see findings) |
| `--project-dir generated/block-dodger` (real M14 output, informational) | 4 rounds fixed `import Phaser from 'phaser'` in StartScene, GameScene, GameOverScene, main.ts (1 line each) → **build ok**. Next failure: a syntax error in the LLM-written `tests/game.spec.ts:58` (stray `)` after `as GameScene`). Round 5: the fixer returned the file unchanged, repair failed → `error` at 5/5 · 199 s. The run's "outside" list only showed my concurrent doc edits. |

## Verification log

| Check | Result |
|---|---|
| fast suite | 298 tests OK (14 skipped gated), 4.9 s |
| `RUN_NPM_TESTS=1 … RealFixturesTest` | base passes; missing-file / win-logic / two-bugs fail with the expected first failure (41 s) |
| `RUN_OLLAMA_TESTS=1 … FixerLLMTest` ×6 after the hardening | 29/30 case runs fixed plausibly (`win-logic` 6/6) |
| full gated suite (`RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1`) | first run: 3 failures (M16 doc not yet in place ×2, fixer raised the timeout on `win-logic`) → hardening → **298 tests OK** in 536 s, including the real two-bugs loop, the real fixtures and the M13 e2e |
| validate_schemas / smoke_graph | ok (9 models) / exit 0, sha256 = baseline `e0ff1d10…` |

## Findings / issues

- **The M15 fixtures do not fail on disk** with the pinned stack on macOS:
  - `import-case`: the filesystem is case-insensitive, so vite resolves `./scenes/gameScene`;
  - `phaser-default`: vite 8.3.1 interop-resolves the default import. The M14 error came from block-dodger's vite ^2.8.

  They stay valid fixer inputs and are marked `fails_for_real=False`. The loop's Done-when uses only cases verified to fail, and a gated test keeps that true.
- **One error per round:** vite reports only the first error, so block-dodger spent 4 of 5 attempts on the same one-line fix in four files. Possible follow-up: tell the fixer to apply the same fix to every file with the same pattern (it may already change up to 3 files).
- **The test writer can emit syntactically invalid tests** (block-dodger line 58). `check_tests` checks rules but does not parse TypeScript, and the fixer could not see the stray `)`. Candidates for later: a syntax check for proposed tests (e.g. esbuild/tsc parse) and pointing the fixer at the failing line.
- **The "tests 0/0 passed" summary** appears when Playwright cannot load the spec file. The failure message is correct; only the count is uninformative.
- **The fixer weakened a test once:** in the first full gated run, real qwen answered the `win-logic` timeout by raising `timeout` in playwright.config.ts (15 s → 30 s) instead of fixing the game. This is now blocked deterministically (see Changes). Afterwards: `FixerLLMTest` 6 runs × 5 cases = 29/30. The miss was `phaser-default` with `content: null` twice: repair cannot add file content it never saw, so the node returns a NodeError. Known flake.
- **No rollback:** a fix that breaks something else costs the next attempt. The budget caps the damage. Every applied change stays visible in `loop_history` and `changed_files`.
- `generated/fix-demo-{phaser-default,missing-file,win-logic,two-bugs}` and the modified `generated/block-dodger` are kept as run outputs (not cleaned up; `generated/` is not git-ignored, so delete them before a commit if they should not be versioned).
