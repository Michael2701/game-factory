# M08 — Coder Node Dry Run

Status: complete (2026-10-11) — awaiting user review

## Scope

`agents/nodes/coder.py` in dry-run mode: one ImplementationTask (+ GameSpec, existing files) → proposed `FileChangeSet`. Never writes files. Runner `scripts/run_coder_dry_run.py` with a filesystem-unchanged proof.

## Done criteria

Given a sample task, the coder proposes valid FileChange objects without modifying the filesystem.

## Changes

- Schema: `FileChangeSet(changes: list[FileChange])` in `agents/schemas/task_plan.py` (+ export, sample, `validate_schemas.py` now 9 models).
- New `agents/nodes/coder.py`: `CODER_KINDS`, `is_coder_task`, `check_changes`, `code_task` (no graph node yet — M13).
- `agents/prompts/__init__.py`: new `format_files()` — files shown to the LLM as `=== path === … === end of path ===` blocks (JSON escaped every newline).
- `agents/prompts/coder.md`: `{{schema}}` is now the `FileChangeSet` schema; rules (one change per allowed path, create/update by existence, no ``` in content, allowed build scripts, allowed libraries); example switched to Target Tapper T3.
- New `scripts/run_coder_dry_run.py`, `tests/test_coder.py` (17 tests, 1 gated); `tests/test_prompts.py` uses `FileChangeSet` and tests `format_files`.
- Docs: NODES, SCHEMAS, PROMPTS, TESTING, ARCHITECTURE, ROADMAP, CLAUDE.md, README, this file.

## Verification log

| Check | Result |
|---|---|
| fast suite (1st run) | 1 failure → existing files reached the prompt as escaped JSON (`"old\\n"`); fixed with `format_files` |
| fast suite | 139 tests OK (6 skipped: LLM) |
| `python scripts/run_coder_dry_run.py` (T3, real model) | exit 0, 12 s, 2 creates (index.html, src/main.ts), **filesystem unchanged: yes (66 files hashed)** |
| T2 / T4 / T5 / T6 | all exit 0 on the first call (no repair), 11 s / **45 s (3 scenes, 139 lines)** / 13 s / 14 s, filesystem unchanged each time |
| `RUN_OLLAMA_TESTS=1 caffeinate -i` full suite | 139 tests OK in ~148 s; smoke_graph sha256 = baseline |

## Code review of the generated code (manual)

Structurally valid, but not yet working code:
- `GameScene` uses `this.physics` while `main.ts` enables no physics; `this.input.on('keydown_LEFT')` is Phaser 2 style (Phaser 3: `this.input.keyboard.on('keydown-LEFT')`); `setVelocityY` on a `Rectangle` does not type-check.
- `testHooks.ts` calls `game.scene.getCurrentScene()` (not a Phaser 3 API) and `spawnBlockOverPlayer()`, which the T4 scene never defines; the hooks are never wired into `main.ts`.
- T3 boots Phaser with `scene: []` because scenes come later — and T4 may not touch `main.ts`, so the scenes would never be registered.
- `package.json` pins old versions (vite ^3, typescript ^4.7).

## Issues / follow-ups

- **Answer to the M5/M7 question:** three scenes in one call are fine for the 14b model (45 s, no repair). Size is not the problem — **cross-task coherence is**: each task is coded in isolation.
- For M13: run tasks in order passing previously proposed files as `existing_files` (already supported), and let integration files (`src/main.ts`) be updated by later tasks (decomposer rule or allowed-paths extension) — to be planned there.
- Code correctness (Phaser API misuse, types) is expected to be caught by build/tests and the fix loop (M10–M16); consider Phaser 3 API hints in the coder prompt if the fixer struggles.
