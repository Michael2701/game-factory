# Safe tools reference

`agents/tools/` is the **only** way agent code touches files or runs commands. Rules come from [SAFETY.md](SAFETY.md).

```python
from agents.tools.filesystem import read_file, write_file, list_files
from agents.tools.commands import run_command          # -> CommandResult (agents.schemas)
from agents.tools.safety import SafetyError, ensure_inside_project, check_command, PROJECT_ROOT
```

Every function takes `root=PROJECT_ROOT`; tests pass a temporary directory so real project files are never written.

## Paths (`agents/tools/safety.py`)

| Function | Rule |
|---|---|
| `ensure_inside_project(path, root)` | relative (to root) or absolute; `resolve()` follows symlinks; result must be inside root. Rejects `~…`, NUL bytes, `..` escapes, symlinks pointing outside. |
| `is_protected(path, root)` | `.git/`, `.venv/`, any `.ssh` segment, names starting `.env` / `id_rsa` / `id_ed25519`, suffixes `.pem` / `.key` / `.p12`. |
| `ensure_allowed_path` | inside **and** not protected — used for every read/list/cwd. |
| `ensure_writable` | allowed **and** below `games/`, `templates/` or `generated/` (`WRITE_ROOTS`), not the root folder itself. |

All failures raise `SafetyError` (a `ValueError`).

## Files (`agents/tools/filesystem.py`)

- `read_file(path)` → `str`; regular file, ≤ 1 MB (`MAX_FILE_BYTES`).
- `write_file(path, content)` → resolved `Path`; only write roots, ≤ 1 MB, creates parent folders, refuses directories.
- `file_hashes(root=PROJECT_ROOT, skip_dirs=SNAPSHOT_SKIP_DIRS)` → `{relative path: sha256}`; prunes `.git`, `.venv`, `node_modules`, `__pycache__`, `.idea`, `dist`. Read-only; dry-run runners use it to prove nothing was written.
- `read_project(project_dir, root)` → `{path relative to project_dir: text}` for a generated project's sources (`.ts .js .html .json .css`), skipping `node_modules/`, `dist/`, test reports, `package-lock.json` and `.factory/` (saved graph state, M18). Read-only; used by the fixer node and the test-writer runner.
- `list_files(path=".", recursive=False)` → sorted relative paths, directories end with `/`; hides `.git`, `.venv`, `node_modules`, `__pycache__`, `.idea`, protected files and symlinks pointing outside.

## Commands (`agents/tools/commands.py`, `check_command`)

`run_command(command, cwd=".", timeout=300)` → `CommandResult`. `command` is a string (`shlex.split`) or argv list. Execution: **no shell** (`shell=False`), env without variables matching `TOKEN|SECRET|KEY|PASSWORD|PASSWD|CREDENTIAL|AUTH`, stdout/stderr keep the last 20 000 chars, timeout → `timed_out=True, exit_code=-1`. Unsafe commands raise `SafetyError` **before** anything runs.

Any token containing `| ; & > < $ \`` or a newline is rejected. Allowlist:

| Requested | Actually runs | Extra checks |
|---|---|---|
| `npm install` | `npm install --ignore-scripts --no-audit --no-fund` | no package arguments; lifecycle scripts never run |
| `npm run build` | `npm run build` | `package.json` `scripts.build` must be one of `vite build`, `tsc && vite build`, `tsc --noEmit && vite build`; no `prebuild`/`postbuild` hooks (`package_json_problems`) |
| `npx playwright test [--reporter=…] [paths]` | `npx --no-install playwright test …` | never downloads; other options rejected; paths allowed |
| `python <file>.py [args]` | `<venv python> <abs file> [args]` | existing `.py` inside the project; no `-c`, `-m`, or options |
| `ls [-l -a -la -al -R] [paths]` | `ls …` | paths allowed (inside, not protected, no `~`) |

Known-dangerous programs (`rm`, `sudo`, `curl`, `wget`, `sh`, `bash`, `zsh`, `chmod`, `chown`, `dd`, `mv`, `cp`, `ssh`, `scp`, `git`, `kill`, `open`, …) are rejected with an explicit reason; everything else not in the table is rejected as "not in the allowlist". `cwd` must be an existing, allowed directory.

## Applying FileChanges (`agents/tools/apply_changes.py`, M9)

```python
preview = apply_changes(change_set, "generated/block-dodger")            # dry run (default)
print(preview.summary())                                               # show before applying
if preview.ok:
    result = apply_changes(change_set, "generated/block-dodger", apply=True)
    result.changed_files                                               # project-relative paths
```

- `target_dir` must be a folder **below** a write root (`generated/x`, not `generated`); `FileChange.path` is relative to it and must stay inside it.
- **All-or-nothing**: every change is validated first; any error → `ApplyResult.errors`, nothing written.
- Rules: `ensure_writable` for every path (symlinks resolved), no duplicates, `create` only for new files, `update`/`delete` only for existing files, `patch` rejected (send full content), ≤ 1 MB, `package.json` must pass `package_json_problems` (valid JSON, allowlisted `scripts.build`, no `prebuild`/`postbuild`).
- An empty change set is a valid no-op.
- The graph's `--apply` flow (M14, `agents/nodes/applier.py`) is stricter on top: target only below `generated/` or `games/`, must be new or empty (no overwrite), and all proposals are merged into one `create` per file before the preview.
- `ApplyResult`: `target_dir`, `dry_run`, `planned[path, operation, bytes, old_bytes]`, `changed_files`, `errors`, `.ok`, `.summary()`.

## Known limits

- `npm run build` and `npx playwright test` still execute project code (vite config, playwright config, test files). package.json scripts are validated (M9); TS/config files cannot be validated statically.
- `npm install` with `--ignore-scripts`: verified to work for vite 8.3.1 + typescript 6.0.3 (M10). If a dependency ever needs its install script, decide explicitly — do not drop the flag silently.
- `npx playwright install` (browser download) stays **not allowed**: generated projects pin `@playwright/test` 1.62.0, whose Chromium (chromium-1234) is already cached on this machine (M12).

## Extending the allowlist

1. Add a branch in `check_command` that returns a **fully normalised argv** (pin flags, forbid free-form options).
2. Validate every path argument with `_arg_path` (inside project, not protected, no `~`).
3. Add accepted + rejected cases to `tests/test_safe_tools.py` and, if user-visible, to `scripts/test_safe_tools.py`; update this table.
