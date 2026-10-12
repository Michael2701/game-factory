# M19 — Phaser Template as Agent Output Target

Status: complete (2026-10-12)

## Scope

Make Phaser + Vite + TypeScript the real target format of generated games: `templates/phaser-vite-template/` (package.json, index.html, src/main.ts, src/scenes/, playwright.config.ts, tests/). It is minimal and testable, and it is used by the agents as their starting point. It is not a hand-built game.

## Done criteria

The agent system can use the template as a target for future generated games. **Met:**
- A project created from the template really installs, builds and passes its 3 smoke tests (gated test + `new_from_template.py --check`).
- The real graph (Ollama) plans on top of the template:
  - no setup/config tasks;
  - the coder updates the template's scenes, main.ts and hooks;
  - the test writer replaces the smoke tests;
  - the applier writes template + proposals.
- The applied Block Dodger builds; Playwright reports 4/7 passing.

## Template

| File | Content | Agents |
|---|---|---|
| `package.json` | `dev: vite`, `build: vite build`; exact pins phaser 3.90.0, vite 8.3.1, typescript 6.0.3, @playwright/test 1.62.0 | locked |
| `index.html` | `#app` + `/src/main.ts`; `<title>` per game | locked |
| `tsconfig.json` | strict, ES2022, bundler, noEmit | locked |
| `playwright.config.ts` | chromium headless, `vite preview` on 41731, timeout 15 s | locked |
| `src/main.ts` | `import * as Phaser`, Arcade Physics, `[StartScene, GameScene]`, `setupTestHooks(game)` | update |
| `src/scenes/StartScene.ts` | "Click to start" → GameScene | update |
| `src/scenes/GameScene.ts` | placeholder with `result` and `skipTime(seconds)` | update |
| `src/testHooks.ts` | `__GAME_STATE__.scene/.result`, `__TEST_API__.startGame()/.skipTime()` | update |
| `tests/game.spec.ts` | 3 smoke tests of the hook contract | replaced by the test writer |
| `README.md` | template docs | not copied |

## Changes

- `templates/phaser-vite-template/` (new, 10 files).
- `agents/generators/phaser_template.py` (new):
  - `template_files` (safe tools, always read from the repo);
  - `instantiate(slug, title)` (package name, html-escaped title);
  - `template_changes`, `project_base(template, …)`;
  - `LOCKED_FILES`;
  - `TEMPLATE_GUIDE` / `EMPTY_GUIDE` (decomposer prompt).
- `GameFactoryState.template`. `run(..., template="phaser-vite-template")` is the default; `template=None` keeps the "from scratch" mode.
- task_decomposer:
  - the prompt gets `{{project_base}}`, and the example is a template plan (Target Tapper);
  - with a template, `check_plan` requires no `config` task and rejects locked files in `target_files`.
- coder:
  - the virtual file system starts from the template; proposals never contain it;
  - the prompt gets `{{locked_paths}}`, the "always `import * as Phaser`" rule and the template-placeholder rule; the example creates GameOverScene and updates the template's main.ts;
  - `check_changes` rejects locked files and always rejects `import Phaser from 'phaser'` (the M14 build failure).
- test_writer:
  - sees template + proposals;
  - **existing tests no longer count as hook definitions** (found in a real run, see findings).
- applier: `final_changes` = template + code + tests.
- **Test runner fix (found in the real run):** the safe command runner keeps only the last 20 000 chars of output. A Playwright JSON report with 9 failing tests is 46 KB, so it was cut and "report not parsed" (the fixer would have seen JSON fragments). Changes:
  - `run_command(..., max_output_chars)`;
  - the test step reads up to `REPORT_MAX_CHARS` (5 MB), parses the full report, and stores only the 20k tail in the state.
- `scripts/new_from_template.py` (new): `--target` (new/empty folder below generated/ or games/), `--slug`, `--title`, `--check`. Exit 0 / 1 (write or checks failed) / 2 (target refused).
- `agents/schemas/examples.py`: `sample_template_task_plan` (validate_schemas: 11 samples). `sample_task_plan` stays the scratch plan.
- Tests:
  - `tests/test_phaser_template.py` (new; 20 fast + 1 gated);
  - `test_graph` now runs on the template (template plan, 5 LLM calls, applied tree = template + GameOverScene, scratch mode);
  - `test_coder` / `test_apply_changes` / `test_graph` replies use `import * as Phaser`;
  - prompt variables;
  - `test_test_runner`: large report regression + limit;
  - `test_safe_tools`: raised output limit.
- Docs: GENERATORS (template section, Phaser pin), ARCHITECTURE, NODES, PROMPTS, SCHEMAS, TESTING, ROADMAP, README, CLAUDE.md, this file.

## Real runs

`python scripts/new_from_template.py --target generated/template-check --check` → 9 files written (4 marked locked); `status: passed (install ok · build ok · tests 3/3 passed)`, exit 0.

`python agents/game_factory_graph.py` (dry run, qwen2.5-coder:14b, 3.5 min) → plan on top of the template, exit status `changes_proposed`:

```
T1  code       Start scene       files: src/scenes/StartScene.ts
T2  code       Game scene        files: src/scenes/GameScene.ts
T3  code       Game over scene   files: src/scenes/GameOverScene.ts
T4  test_hooks Test hooks        files: src/testHooks.ts
T5  tests      Playwright tests  files: tests/game.spec.ts
T6  build · T7 run_tests
UPDATE src/scenes/StartScene.ts · UPDATE src/scenes/GameScene.ts · CREATE src/scenes/GameOverScene.ts
UPDATE src/main.ts · UPDATE src/testHooks.ts · UPDATE tests/game.spec.ts
```

(The CLI's "filesystem unchanged" said NO for this run only because `new_from_template.py` was writing `generated/template-check` at the same time. The gated `GraphLLMTest` repeats the dry run alone and checks the hashes.)

Applied runs (`--apply`, then the test runner), for information; fixing them is the loop's job in M20:

| Run | Result | What it showed |
|---|---|---|
| `generated/block-dodger-m19` | build ok, report "not parsed" → after the runner fix: tests 1/9 | `this.physics.add…` crashed every scene: **the template had no physics enabled** → Arcade Physics added to the template's main.ts (+ test) |
| `block-dodger-m19b` | test writer NodeError (tests used `__GAME_STATE__.playerX`, which no hook defines; repair did not help) | the hook check also counted the template's old smoke tests as hook sources → fixed (+ test). The empty folder of this failed run was removed. |
| `generated/block-dodger-m19c` | **build ok · tests 4/7 passed** | remaining failures are game logic: after a hit or `skipTime(60)` the game stays in GameScene instead of GameOverScene |

All runs: files changed outside the target: 0.

## Verification log

| Check | Result |
|---|---|
| fast suite | 379 tests OK (17 skipped gated) |
| `RUN_NPM_TESTS=1 … test_phaser_template.RealTemplateTest` | OK: template project builds, 3/3 tests, `dist/index.html` |
| full gated suite (`RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1`) | **379 tests OK, 0 skipped**, 573 s: real template project 3/3, real dry run on the template (`GraphLLMTest`, filesystem unchanged), real two-bugs loop + gate, real reviewer / fixer / test writer tests |
| validate_schemas / smoke_graph | ok (11 samples) / exit 0, sha256 = baseline `e0ff1d10…` |

## Findings / issues

- **The template removes the M14 failure class.** Versions are pinned and locked, and the default import is rejected deterministically. All three applied runs built (`build ok`) on the first try.
- **Two test-tool bugs only showed up with a real, larger generated project:**
  - the 20k output tail cut the Playwright JSON report;
  - old tests counted as hook definitions.

  Both are fixed and have regression tests.
- **The generated hooks can be wrong at runtime.** m19 had `this.add.rectangle` inside the `__TEST_API__` object, where `this` is not the scene. The static checks cannot see this. The fix loop (test failures → fixer) is the intended remedy (M20).
- **The test writer still sometimes invents hooks** (m19b). The deterministic check catches it, but one repair is not always enough. This is a known flake from M13, now with a cleaner hint.
- Game logic quality (4/7 in m19c) is what M20 has to close with the fix loop + reviewer + human gate.
- `generated/template-check`, `generated/block-dodger-m19` and `generated/block-dodger-m19c` are kept as run outputs.
