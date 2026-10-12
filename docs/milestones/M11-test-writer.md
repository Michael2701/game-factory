# M11 — Test Writer Node Dry Run

Status: complete (2026-10-11) — awaiting user review

## Scope

`agents/nodes/test_writer.py` in dry-run mode: GameSpec (+ existing project files) → proposed Playwright tests as a `FileChangeSet` (`tests/game.spec.ts`, optionally a new `playwright.config.ts`). Never writes files. Tests prefer `window.__GAME_STATE__` / `window.__TEST_API__`.

## Done criteria

The node proposes a valid `tests/game.spec.ts` file as a structured FileChange.

## Changes

- New `agents/nodes/test_writer.py`: `write_tests`, `check_tests` (file rules; imports only `@playwright/test`; forbidden `waitForTimeout`/`setTimeout`/`Math.random`/`sleep(`/`require(`/`child_process`; ≥ 3 tests; only `page.goto('/')`; must read `__GAME_STATE__`; must use `__TEST_API__` when the spec does).
- `agents/prompts/test_writer.md`: FileChangeSet schema, `format_files` context, Target Tapper example, rules matching the checks + 4 rules added after the real-model review (see log).
- New `agents/tools/filesystem.py::file_hashes` (prunes node_modules/dist/.git/.venv; ~2 ms for the project); `scripts/run_coder_dry_run.py` uses it.
- New `scripts/run_test_writer_dry_run.py` (`--spec`, `--project-dir` read-only, `--json`), `tests/test_test_writer.py` (17 tests, 1 gated).
- Docs: NODES, PROMPTS, TOOLS, TESTING, ARCHITECTURE, ROADMAP, CLAUDE.md, README, this file.

## Verification log

| Check | Result |
|---|---|
| fast suite | 190 tests OK (8 skipped) |
| Block Dodger, run 1 (real model) | exit 0, 35 s, 7 tests, passes `check_tests`, TS syntax ok (`ts.transpileModule`), filesystem unchanged — **but semantically broken**: win tests wait 60 s of real time for `timeLeft === 0` (Playwright times out at 30 s), one test waits for `isGameOver` without causing it, win only asserted via scene, 2 duplicate pairs |
| prompt: +4 rules (cause the awaited state; `skipTime(seconds)` for timers; assert `result`; no duplicates; name missing hooks clearly) | prompt/unit tests green |
| Block Dodger, run 2 | exit 0, 16 s, 3 clean tests (loads / `skipTime(60)` → `result === 'win'` / `spawnBlockOverPlayer` → `result === 'lose'`), syntax ok, filesystem unchanged |
| snake (planner spec) + `--project-dir generated/sample-game` | exit 0, 23 s, 4 tests, syntax ok, project files shown as context, filesystem unchanged |
| `RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1 caffeinate -i` full suite | 190 tests OK in ~205 s (0 skipped); smoke_graph sha256 = baseline |

## Issues / follow-ups

- Static checks cannot prove test *semantics*; real runs (M12) and the fix loop (M16) are the backstop.
- The test writer introduces hooks not in the spec (`startGame()`, `skipTime()`, `collideWithWall()`) → the coder must implement the hooks the tests use. Same cross-task coherence problem as M8 — M13 should feed the proposed test file to the coder (or derive a hook contract).
- Snake "eat apple" test assumes the apple at (100,100) is one step right of the snake — geometry-dependent; better hooks (e.g. `spawnAppleAhead()`) would be deterministic. Candidate prompt rule if it fails in M12+.
- fixer prompt still uses the per-item `FileChange` schema and a Block Dodger-like example — update in M15.
