# Safety rules

Applies to Claude working in this repo **and** to the agent tools the system will expose to the LLM.

## For Claude (development)

- Work only inside `/Users/michaelsilianov/Projects/game-factory`.
- Do not access or modify `~/.ssh`, global config files, credentials, `.env` files outside this project, other/work repositories, or system folders.
- No destructive commands (`rm -rf`, `sudo`, `git reset --hard`, force pushes, …).
- Do not delete existing files unless explicitly asked.
- Do not modify `agents/smoke_graph.py` unless explicitly asked (a test pins its sha256).
- Prefer small, safe changes. Before large changes, explain what will be done.
- Show changes via `git diff` / summaries in milestone reports.
- Do not install new dependencies without stating why in the plan.

## For agent tools (implemented in `agents/tools/` — see [TOOLS.md](TOOLS.md))

- **Path guard**: every path is resolved (symlinks included) and must stay inside the project root; absolute paths outside are rejected; `~/.ssh` and secret-like files are rejected.
- **Write targets**: generated code may only be written to `games/`, `templates/`, `generated/`.
- **Command allowlist** (initial): `npm install`, `npm run build`, `npx playwright test`, python scripts inside this project, safe listing commands.
- **Always rejected**: `rm -rf`, `sudo`, `curl … | sh`, writes outside the project, reading secrets, changing global configs.
- Commands return `stdout`, `stderr`, `exit code` — never silently swallowed.
- LLM nodes propose `FileChange` objects; only the deterministic applier (`agents/tools/apply_changes.py`) writes, and only with `apply=True` / `--apply`. Validation is all-or-nothing.
- `package.json` written by the LLM: `scripts.build` must be allowlisted and `prebuild`/`postbuild` hooks are forbidden (npm would run them on `npm run build`).
