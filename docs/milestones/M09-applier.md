# M09 — File Change Applier

Status: complete (2026-10-11) — awaiting user review

## Scope

`agents/tools/apply_changes.py`: the only path from proposed `FileChange`s to disk. Validate all paths, write only below games/ templates/ generated/, summary before applying, dry run (default) and apply, return the changed files. Plus the M6 follow-up: validate package.json content.

## Done criteria

A test script creates a sample FileChange, shows dry-run output, applies it to a safe test folder, and rejects unsafe paths.

## Changes

- New `agents/tools/apply_changes.py`: `apply_changes(changes, target_dir, *, apply=False, root)` → `ApplyResult` (`planned`, `changed_files`, `errors`, `.ok`, `.summary()`), `PlannedChange`.
- `agents/tools/safety.py`: new shared `package_json_problems(text, require_build)`; **`npm run build` now also rejects `prebuild`/`postbuild` hooks** (they ran arbitrary commands — gap in M6).
- New `scripts/test_apply_changes.py` (17 PASS/FAIL checks in a temp sandbox), `tests/test_apply_changes.py` (17 tests), +1 test in `tests/test_safe_tools.py`.
- Docs: TOOLS (applier section), SAFETY, CLAUDE.md, ROADMAP, ARCHITECTURE, TESTING, README, this file.

## Verification log

| Check | Result |
|---|---|
| `python scripts/test_apply_changes.py` first run | crashed: `FileChange("../../../x")` is already rejected by the schema, so the applier was never reached → applier checks now use forged objects (`model_construct`), schema rejection checked separately |
| `python scripts/test_apply_changes.py` | 17/17 PASS: dry run writes nothing, apply writes + lists files, update re-apply, 11 rejections with nothing written |
| fast suite | 157 tests OK (6 skipped: LLM) |
| coder → applier integration (FakeLLM) | preview ok, nothing written; apply writes `generated/block-dodger/{index.html,src/main.ts}` in the sandbox |
| `RUN_OLLAMA_TESTS=1 caffeinate -i` full suite | 157 tests OK in ~171 s; smoke_graph sha256 = baseline; no `generated/` folder created in the real project |

## Issues / follow-ups

- `patch` changes are rejected ("send the full content"); add unified-diff support only if the fixer (M15) needs it.
- Writes are validated all-or-nothing, but the write phase itself is not transactional (an OS error mid-way could leave partial writes) — acceptable for generated folders.
- Delete is supported (only inside the target folder); no node proposes deletes yet.
