# M10 — Minimal Target Project Generator

Status: complete (2026-10-11) — awaiting user review

## Scope

Deterministic generator for a minimal Vite + TS target project (`generated/sample-game/`: package.json, index.html, src/main.ts) built from FileChange objects → applier → `npm install` + `npm run build` through the safe tools. First real npm network install. Reference: [GENERATORS.md](../GENERATORS.md).

## Done criteria

The tooling generates `generated/sample-game/` using FileChange objects and runs `npm install` and `npm run build` successfully.

## Changes

- New package `agents/generators/` with `minimal_project.py` (`minimal_project_changes`, `generate_minimal_project`, `GenerationReport`; pins vite 8.3.1, typescript 6.0.3).
- New `scripts/generate_sample_game.py`, `tests/test_minimal_project.py` (16 tests; 1 gated by new `RUN_NPM_TESTS=1`).
- `.gitignore`: `dist/`. `tests/test_task_decomposer.py::project_snapshot` skips `node_modules`/`dist`.
- Generated artifact: `generated/sample-game/` (package.json, index.html, src/main.ts, package-lock.json, node_modules, dist).
- Docs: new GENERATORS.md, this file; updated CLAUDE.md, README, ROADMAP, ARCHITECTURE, TESTING, TOOLS.

## Verification log

| Check | Result |
|---|---|
| `python scripts/generate_sample_game.py --dry-run` | 3 CREATE lines, nothing written |
| fast suite | 173 tests OK (7 skipped: LLM/npm) |
| `RUN_NPM_TESTS=1` sandbox test | install + build exit 0 in ~7 s, `dist/index.html` present, title in built JS |
| `python scripts/generate_sample_game.py` (run 1) | preview shown first; 3 files written; `npm install` ok (17 packages, 0.7 s, **with `--ignore-scripts`**); `npm run build` ok (vite 8.3.1, 4 modules, 22 ms); `dist/index.html` + `dist/assets/index-*.js`; exit 0 |
| run 2 (idempotence) | 3 UPDATE (same sizes), install + build ok, exit 0 |
| `RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1 caffeinate -i` full suite | 173 tests OK in ~153 s (0 skipped); smoke_graph sha256 = baseline; `generated/` contains only `sample-game` |

## Issues / follow-ups

- npm `latest` phaser is 4.2.1; prompts/model assume Phaser 3 → pin 3.x in M19 (and tell the coder prompt which major version).
- `vite build` does not type-check. For the agent loop (catching LLM type errors like those seen in M8), the Phaser template (M19) should use `tsc --noEmit && vite build` with a tsconfig.
- npm writes its cache to `~/.npm` (outside the project) — normal npm behaviour, not controlled by the safe tools.
