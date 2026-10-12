# M15 — Fixer Node

Status: complete (2026-10-11)

## Scope

`fixer_node`: failing TestResult + relevant files + GameSpec + TaskPlan → proposed minimal FileChanges. Minimal changes only, no rewrites, no unrelated files, respect `max_fix_attempts`. The node never writes; applying fixes and the loop are M16.

## Done criteria

Given a synthetic failing test result, `fixer_node` proposes a plausible minimal fix.

## Changes

- `agents/nodes/fixer.py` (new):
  - `mentioned_paths` / `relevant_files`: the files named in the failure output (also inside absolute paths), plus `package.json` and `src/main.ts`. If the failure names no `src/` file (e.g. a failing Playwright test), every project file is relevant. Named files that do not exist may be created.
  - `check_fix` (errors feed the repair prompt):
    - only relevant files may be updated and only creatable files created; no delete, no patch;
    - ≤ 3 files; ≤ max(20, 40 % of the file) changed lines per file (difflib); no identical "updates";
    - `tests/*.spec.ts` must not lose `test(...)` calls or gain `test.skip/only/fixme`;
    - package.json safety rules (`package_json_problems`, build script required); no code fences;
    - an empty proposal is valid ("no safe fix").
  - `fix(...)`: prompt + `invoke_structured`. The prompt gets a compact TestResult view (failed commands + failure messages, no install logs).
  - `fixer_node(state, llm, root)`: reads `state.target_dir` with `read_project` (read-only).
    - No LLM call when there is no TestResult, the result passed, the result is `error` (not fixable by code), `fix_attempts >= max_fix_attempts`, or the target is missing/unsafe.
    - Otherwise it increments `fix_attempts` (also on NodeError / empty proposal) and sets `fix_changes` + status `fixing`.
- State: `fix_changes: list[FileChange]`.
- Prompt `fixer.md`:
  - `{{schema}}` is now `FileChangeSet`;
  - new inputs `{{project_tree}}` (all paths, no content) and `{{new_files}}`;
  - rules for create/update and the minimality limits;
  - Target Tapper example (was Block Dodger-like).
- `agents/tools/filesystem.py`: `read_project` (moved from the test-writer runner, now shared).
- `agents/fixtures/broken_projects.py` (new): base Phaser + Vite project in memory plus two cases with one bug each, the failing TestResult and a deterministic `is_fixed` check.
  - `import-case`: `./scenes/gameScene` vs `GameScene.ts`.
  - `phaser-default`: `import Phaser from 'phaser'`, the real M14 error.
- `scripts/run_fixer_dry_run.py` (new): `--case` or `--project-dir` (runs the real test runner first). Prints the failure, relevant files, the proposed fix as a unified diff, plausibility (cases) and the filesystem-unchanged proof.
- Tests: `tests/test_fixer.py` (new, 24 + 1 gated); `tests/test_prompts.py` updated for the fixer variables/schema.
- Docs: NODES, PROMPTS, SCHEMAS, TOOLS, TESTING, ARCHITECTURE, ROADMAP, README, CLAUDE.md, this file.

## Sample input / output

Input (case `phaser-default`): `npm run build` failed with

```
'default' is not exported by node_modules/phaser/dist/phaser.esm.js, imported by src/scenes/StartScene.ts
file: /project/generated/dodge-demo/src/scenes/StartScene.ts:1:7
```

Relevant files: `src/scenes/StartScene.ts`, `package.json`, `src/main.ts`. Output (real qwen, 13 s):

```
UPDATE src/scenes/StartScene.ts  (2 changed lines)
reason: Build failed: 'default' is not exported by node_modules/phaser/dist/phaser.esm.js ... — use * as Phaser import instead
-import Phaser from 'phaser';
+import * as Phaser from 'phaser';
plausible fix (culprit src/scenes/StartScene.ts fixed): yes
```

Case `import-case` (11 s): `-import { GameScene } from './scenes/gameScene';` → `+import { GameScene } from './scenes/GameScene';`.

## Verification log

| Check | Result |
|---|---|
| fast suite | 270 tests OK (12 skipped gated) |
| `python scripts/run_fixer_dry_run.py --case phaser-default` | exit 0, 1-line fix, plausible, filesystem unchanged |
| `python scripts/run_fixer_dry_run.py --case import-case` | exit 0, 1-line fix, plausible, filesystem unchanged |
| `python scripts/run_fixer_dry_run.py --project-dir generated/block-dodger` (real M14 project) | test runner: install ok, build failed (Phaser default import in StartScene.ts) → the same 1-line fix, filesystem unchanged by the fixer (14.8 s) |
| `RUN_OLLAMA_TESTS=1 … tests.test_fixer.FixerLLMTest` ×3 | 3/3 OK (6/6 cases fixed plausibly) |
| `RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1` full suite | **270 tests OK** in 430 s (incl. real e2e dry run, real fixer cases, npm builds, Playwright); validate_schemas ok; smoke_graph sha256 = baseline |

## Issues / follow-ups

- Before `project_tree` was added, the model only saw main.ts + package.json for the casing case, so it could not know the real file name. Now every prompt lists all project paths (no content).
- The build reports one error at a time. In generated/block-dodger every scene uses the default Phaser import, so the loop (M16) will need several attempts (one file per attempt) unless the fixer generalises. Allowed: up to 3 files per fix if the error shows them.
- The 20 lines / 40 % budget is a heuristic. All real fixes so far were 2 changed lines; revisit if M16 hits legitimate larger fixes.
- `is_fixed` checks are lexical (enough to judge plausibility, not a build). M16 proves fixes by rebuilding.
- **M16 finding:** on disk, with the pinned stack on macOS, both M15 cases build and pass. `import-case`: the filesystem is case-insensitive. `phaser-default`: vite 8.3.1 interop-resolves the default import; the M14 error came from block-dodger's vite ^2.8. They stay valid fixer inputs (the failure text is real) and are marked `fails_for_real=False`. M16 adds cases that really fail: `missing-file`, `win-logic` and `two-bugs`.
