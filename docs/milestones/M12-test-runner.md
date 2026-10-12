# M12 — Command Runner Node

Status: complete (2026-10-11) — awaiting user review

## Scope

`agents/nodes/test_runner.py`: run `npm install`, `npm run build`, `npx playwright test` on a generated project through the safe tools and return a structured `TestResult` (deterministic, no LLM). Runner `scripts/run_test_runner.py`.

## Done criteria

The node can run npm build in `generated/sample-game/` and return structured CommandResult/TestResult.

## Changes

- New `agents/nodes/test_runner.py`: `run_project_checks(project_dir, steps)`, `parse_playwright_json`, `test_runner_node(state, project_dir=None)` (default `generated/<slug>`), `default_project_dir`.
- Status semantics: `passed` / `failed` (non-zero exit → fixable) / `error` (cannot run: missing project, SafetyError, timeout). Failure messages: stderr + stdout tail (40 lines), ANSI stripped, node_modules stack frames removed; Playwright failures one per failed test (`file › suite › title`).
- New `scripts/run_test_runner.py`, `tests/test_test_runner.py` (20 tests, 3 gated by `RUN_NPM_TESTS`).
- Docs: NODES, SCHEMAS, GENERATORS, TOOLS, TESTING, ARCHITECTURE, ROADMAP, CLAUDE.md, README, this file.

## Key finding: Playwright without browser downloads

`~/Library/Caches/ms-playwright/chromium-1234` was installed by playwright-core **1.62.0** (July, via npx). Pinning `@playwright/test` **1.62.0** in generated projects runs real browser tests with the cached Chromium — no `npx playwright install`, no allowlist change (question open since M6). Verified: cache unchanged after the real run.

## Verification log

| Check | Result |
|---|---|
| `python scripts/run_test_runner.py` (Done when) | `npm install` ok 0.1 s, `npm run build` ok 0.2 s on `generated/sample-game`; status `passed`; summary `install ok · build ok · no tests found (tests/*.spec.ts)`; `--json` prints both CommandResults |
| mocked unit tests | statuses, stop at first failure, timeout/SafetyError → error, JSON parsing (nested suites, ANSI), fallback, node state updates |
| real sandbox: minimal project | `passed` |
| real sandbox: `src/main.ts` = `const x = ;` | `failed`, failure `npm run build` with `[vite] Unexpected token … src/main.ts:1:11` |
| failure message review | half of it was a node_modules stack trace → frames filtered (+ test) |
| **real Playwright**: @playwright/test 1.62.0 + config (`vite preview` web server) + 2 tests (1 deliberately failing) | `failed`, exactly `game.spec.ts › deliberately failing` reported with the expected/received message, summary `tests 1/2 passed`; ~10 s; browser cache untouched |
| `RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1 caffeinate -i` full suite | 210 tests OK in ~197 s (0 skipped); smoke_graph sha256 = baseline |

## Issues / follow-ups

- The Playwright config used in the test (webServer `npx vite preview`, baseURL, chromium) is the template for M19 — move it into the Phaser template there.
- `npm install` runs on every check (fast when up to date: ~0.1 s).
- Playwright JSON output larger than the 20 000-char command output limit would be truncated → falls back to a single failure with the output tail (unlikely for small games).
