# M06 — Safe Tool Layer

Status: complete (2026-10-11) — awaiting user review

## Scope

Safe local file and command tools for agents (reference: [TOOLS.md](../TOOLS.md)): `read_file`, `write_file`, `list_files`, `ensure_inside_project`, `run_command`; command allowlist; `scripts/test_safe_tools.py` proof script. No LLM involved.

## Done criteria

`scripts/test_safe_tools.py` proves: valid project paths work, outside paths are rejected, safe commands work, dangerous commands are rejected.

## Changes

- New: `agents/tools/safety.py`, `agents/tools/filesystem.py`, `agents/tools/commands.py`, `scripts/test_safe_tools.py`, `tests/test_safe_tools.py` (27 tests).
- Fixed M2 schemas (bug found by M6 tests): `StrictModel` strips whitespace from all strings, which corrupted `FileChange.content`/`patch` (lost trailing newlines / patch context) and `CommandResult.stdout`/`stderr`. Both models now keep whitespace; `FileChange.path` is trimmed explicitly. +3 schema tests.
- Docs: new `docs/TOOLS.md`, this file; updated SAFETY, SCHEMAS, CLAUDE.md, ROADMAP, ARCHITECTURE, TESTING, README.

## Verification log

| Check | Result |
|---|---|
| `python scripts/test_safe_tools.py` | 25/25 checks PASS, exit 0 (sandbox in a temp dir) |
| `tests/test_safe_tools.py` first run | 2 failures → found: `ls ~` not rejected (harmless without shell, now rejected explicitly) and the whitespace-stripping schema bug |
| self-review | `list_files(recursive=True)` would crash on a symlink pointing outside → now skipped; covered by test |
| real execution | `npm install` (offline, empty package.json) exit 0; `npm run build` failure captured; timeout, exit codes, output truncation, secret env scrubbing verified |
| fast suite | 107 tests OK (4 skipped: LLM) |
| `RUN_OLLAMA_TESTS=1` full suite | 107 tests OK; project file hashes identical before/after; smoke_graph sha256 = baseline. Wall time was ~17 min because macOS idle-slept 13:16–13:31 mid-generation (ollama 0.97 tok/s vs ~29 normally; confirmed in `pmset -g log`) — not a code issue |

## Issues / follow-ups

- Build/test commands still execute project code — M9 applier must validate `package.json` scripts and config files it writes.
- `npx playwright install` not allowed yet — decide in M12.
- `npm install --ignore-scripts` may break a dependency that needs install scripts — handle explicitly if it happens (M10).
