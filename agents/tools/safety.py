"""Safety checks for agent tools: path guard, protected paths, command allowlist.

Every filesystem or command access by agents goes through these checks.
Reference: docs/TOOLS.md, docs/SAFETY.md.
"""

import json
import shlex
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Generated code may only be written below these top-level folders.
WRITE_ROOTS = ("games", "templates", "generated")

PROTECTED_DIRS = {".git", ".venv", ".ssh"}
PROTECTED_NAME_PREFIXES = (".env", "id_rsa", "id_ed25519")
PROTECTED_SUFFIXES = (".pem", ".key", ".p12")

SHELL_METACHARS = set("|;&><$`\n")

# Programs refused with an explicit reason (the allowlist below is still the authority).
DANGEROUS_PROGRAMS = {
    "rm", "rmdir", "sudo", "su", "curl", "wget", "sh", "bash", "zsh", "fish", "chmod", "chown",
    "dd", "mkfs", "mv", "cp", "ssh", "scp", "git", "kill", "pkill", "eval", "exec", "open",
}

ALLOWED_BUILD_SCRIPTS = ("vite build", "tsc && vite build", "tsc --noEmit && vite build")
LS_FLAGS = {"-l", "-a", "-la", "-al", "-R"}


class SafetyError(ValueError):
    """Raised when a path or command is not allowed."""


def ensure_inside_project(path: str | Path, root: Path = PROJECT_ROOT) -> Path:
    """Resolve `path` (relative to `root`, or absolute) and require it to stay inside `root`."""
    raw = str(path)
    if "\0" in raw:
        raise SafetyError("path contains a NUL byte")
    if raw.startswith("~"):
        raise SafetyError(f"home-relative paths are not allowed: {raw}")
    root = Path(root).resolve()
    candidate = Path(raw)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()  # follows symlinks
    if not resolved.is_relative_to(root):
        raise SafetyError(f"path is outside the project: {raw}")
    return resolved


def is_protected(path: Path, root: Path = PROJECT_ROOT) -> bool:
    """True for paths inside the project that agents must never read or write."""
    rel = Path(path).resolve().relative_to(Path(root).resolve())
    if PROTECTED_DIRS & set(rel.parts):
        return True
    name = rel.name
    return name.startswith(PROTECTED_NAME_PREFIXES) or name.endswith(PROTECTED_SUFFIXES)


def ensure_allowed_path(path: str | Path, root: Path = PROJECT_ROOT) -> Path:
    resolved = ensure_inside_project(path, root)
    if is_protected(resolved, root):
        raise SafetyError(f"path is protected: {path}")
    return resolved


def ensure_writable(path: str | Path, root: Path = PROJECT_ROOT) -> Path:
    resolved = ensure_allowed_path(path, root)
    rel = resolved.relative_to(Path(root).resolve())
    if not rel.parts or rel.parts[0] not in WRITE_ROOTS or len(rel.parts) < 2:
        raise SafetyError(f"writing is only allowed below {list(WRITE_ROOTS)}: {path}")
    return resolved


def package_json_problems(text: str, require_build: bool = False) -> list[str]:
    """Safety rules for a package.json (written by an LLM). Empty list = ok.

    `npm run build` runs scripts.build AND the npm hooks prebuild/postbuild, so all three
    are restricted. Other scripts never run through the safe tools (npm install uses
    --ignore-scripts).
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"package.json is not valid JSON ({exc.msg} at line {exc.lineno})"]
    scripts = data.get("scripts", {}) if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return ["package.json: 'scripts' must be an object"]
    problems = []
    build = scripts.get("build")
    if (build is not None or require_build) and build not in ALLOWED_BUILD_SCRIPTS:
        problems.append(f"package.json: scripts.build {build!r} is not one of {list(ALLOWED_BUILD_SCRIPTS)}")
    for hook in ("prebuild", "postbuild"):
        if hook in scripts:
            problems.append(f"package.json: scripts.{hook} is not allowed (npm runs it with 'npm run build')")
    return problems


def _check_build_script(cwd: Path) -> None:
    try:
        text = (cwd / "package.json").read_text()
    except OSError as exc:
        raise SafetyError(f"npm run build: cannot read package.json ({exc})") from exc
    problems = package_json_problems(text, require_build=True)
    if problems:
        raise SafetyError("npm run build: " + "; ".join(problems))


def _arg_path(cwd: Path, arg: str, root: Path) -> Path:
    """Resolve a command argument path relative to cwd; must be allowed (inside, not protected)."""
    if arg.startswith("~"):
        raise SafetyError(f"home-relative paths are not allowed: {arg}")
    return ensure_allowed_path(cwd / arg, root)


def check_command(command: str | list[str], cwd: str | Path = ".", root: Path = PROJECT_ROOT) -> list[str]:
    """Validate a command against the allowlist; return the exact argv to run (no shell)."""
    argv = shlex.split(command) if isinstance(command, str) else list(command)
    if not argv:
        raise SafetyError("empty command")
    for token in argv:
        if SHELL_METACHARS & set(token):
            raise SafetyError(f"shell metacharacters are not allowed: {token!r}")

    cwd_path = ensure_allowed_path(cwd, root)
    if not cwd_path.is_dir():
        raise SafetyError(f"cwd is not a directory: {cwd}")

    program, args = Path(argv[0]).name, argv[1:]
    if program in DANGEROUS_PROGRAMS:
        raise SafetyError(f"command '{program}' is not allowed (dangerous)")

    if program == "npm" and args == ["install"]:
        return ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"]

    if program == "npm" and args == ["run", "build"]:
        _check_build_script(cwd_path)
        return ["npm", "run", "build"]

    if program == "npx" and args[:2] == ["playwright", "test"]:
        for arg in args[2:]:
            if arg.startswith("--reporter="):
                continue
            if arg.startswith("-"):
                raise SafetyError(f"npx playwright test: option {arg!r} is not allowed")
            _arg_path(cwd_path, arg, root)
        return ["npx", "--no-install", "playwright", "test", *args[2:]]

    if program in ("python", "python3") and args:
        script, *script_args = args
        if script.startswith("-"):
            raise SafetyError(f"python option {script!r} is not allowed; only project .py files")
        script_path = _arg_path(cwd_path, script, root)
        if script_path.suffix != ".py" or not script_path.is_file():
            raise SafetyError(f"python: {script} is not a .py file in the project")
        return [sys.executable, str(script_path), *script_args]

    if program == "ls":
        out = ["ls"]
        for arg in args:
            if arg.startswith("-"):
                if arg not in LS_FLAGS:
                    raise SafetyError(f"ls option {arg!r} is not allowed")
            else:
                _arg_path(cwd_path, arg, root)
            out.append(arg)
        return out

    raise SafetyError(f"command is not in the allowlist: {' '.join(argv)}")
