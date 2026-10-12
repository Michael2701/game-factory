# Generators reference

Deterministic (non-LLM) generators in `agents/generators/` produce **target project files** as `FileChange` objects. They define the output format the agents will later generate, and they always write through the applier and run commands through the safe tools ([TOOLS.md](TOOLS.md)).

## Minimal target project (M10) — `agents/generators/minimal_project.py`

Plain Vite + TypeScript placeholder (no Phaser yet). Files:

| File | Content |
|---|---|
| `package.json` | private, `"type": "module"`, scripts `dev: vite`, `build: vite build`; devDependencies **exact pins** `vite` + `typescript` |
| `index.html` | `<div id="app">`, `<script type="module" src="/src/main.ts">` |
| `src/main.ts` | typed placeholder: writes the title into `#app`, sets `window.__GAME_STATE__ = { ready: true, title }` (first test hook) |

API:

```python
from agents.generators.minimal_project import minimal_project_changes, generate_minimal_project

changes = minimal_project_changes("sample-game", "Sample Game", existing={"package.json"})  # update vs create
report = generate_minimal_project("generated/sample-game")   # preview → apply → npm install → npm run build
report.ok, report.error, report.preview.summary(), report.commands, report.dist_files
```

- `generate_minimal_project(target, *, slug, title, apply=True, install=True, build=True, root)` — preview via `apply_changes` (dry run), apply, `npm install` (600 s), `npm run build` (300 s); stops at the first failure; requires `dist/index.html`. `apply=False` = preview only.
- Re-running is idempotent: existing files become `update` changes.
- CLI: `python scripts/generate_sample_game.py [--target generated/x] [--dry-run] [--no-install] [--no-build]` (exit 0 only on full success, 2 for a rejected target).

## Phaser template (M19) — `templates/phaser-vite-template/` + `agents/generators/phaser_template.py`

The agents' **output target**: every generated project starts from this template. It is a minimal, testable scaffold, not a game.

| File | Content | Agents |
|---|---|---|
| `package.json` | `dev: vite`, `build: vite build`; exact pins (table below) | **locked** |
| `index.html` | `#app` + `/src/main.ts`; `<title>` filled in per game | **locked** |
| `tsconfig.json` | strict, ES2022, bundler resolution, noEmit | **locked** |
| `playwright.config.ts` | chromium headless, `vite preview` on port 41731, timeout 15 s | **locked** |
| `src/main.ts` | `import * as Phaser`, `Phaser.Game` with Arcade Physics and `[StartScene, GameScene]`, `setupTestHooks(game)` | update (register scenes) |
| `src/scenes/StartScene.ts` | "Click to start" → GameScene | update |
| `src/scenes/GameScene.ts` | placeholder with `result` and `skipTime(seconds)` | update |
| `src/testHooks.ts` | hook contract: `__GAME_STATE__.scene/.result`, `__TEST_API__.startGame()/.skipTime()` | update (test_hooks task) |
| `tests/game.spec.ts` | 3 smoke tests of the contract | replaced by the test writer |
| `README.md` | template docs | not copied |

API (`agents/generators/phaser_template.py`):

```python
template_files()                        # {path: text} read through the safe tools (always from the repo)
instantiate("my-game", "My Game")       # + package name and page title
template_changes(slug, title)           # as `create` FileChanges
project_base(state.template, slug, title)   # {} without a template
LOCKED_FILES, TEMPLATE_GUIDE (decomposer prompt `project_base`), DEFAULT_TEMPLATE
```

In the graph (`run(..., template="phaser-vite-template")`, the default): the decomposer gets the template guide (no setup/config tasks, locked files never targets), the coder and test writer see the template as existing files (so they update them; locked files are rejected), and the applier writes template + proposals into the new project folder. `template=None` keeps the pre-M19 "from scratch" mode.

CLI: `python scripts/new_from_template.py --target generated/x [--slug s] [--title t] [--check]` writes the instantiated template into a new/empty folder (applier preview → write); `--check` runs install → build → Playwright (exit 0 only when the 3 smoke tests pass).

## Version pins

Chosen 2026-10-11, each release ≥ 2 weeks old, exact versions (no `^`) for reproducible installs:

| Package | Pin | Why |
|---|---|---|
| vite | 8.3.1 (2026-09-24) | current stable line; engines node ≥ 22.12 (we have 24.16); builds fine with `npm install --ignore-scripts` |
| typescript | 6.0.3 | last JS-based compiler; TS 7.x is the new native (Go) compiler — avoid until needed |
| @playwright/test | **1.62.0** (M12) | matches the browser already cached at `~/Library/Caches/ms-playwright/chromium-1234` → real tests run without `npx playwright install`; a different version would need a browser download (not allowlisted) |
| phaser | **3.90.0** (M19, Phaser template) | npm `latest` is 4.2.1, but prompts and the model assume **Phaser 3**. 3.90's ESM build has **no default export**: always `import * as Phaser from 'phaser'` (the coder rejects the default import) |

To bump a version: change the constant in `minimal_project.py`, run `RUN_NPM_TESTS=1 python -m unittest tests.test_minimal_project`, regenerate `generated/sample-game`.

## Generated output

`generated/` is the agents' write target (with `games/`, `templates/`). The whole `generated/` folder is git-ignored (only `.gitkeep` is versioned): its projects are run outputs that can be regenerated at any time; the milestone docs record what each run produced.
