"""Safe file operations for agents. All paths are checked by agents.tools.safety.

Reference: docs/TOOLS.md.
"""

import hashlib
import os
from pathlib import Path

from agents.tools.safety import (
    PROJECT_ROOT,
    SafetyError,
    ensure_allowed_path,
    ensure_writable,
    is_protected,
)

MAX_FILE_BYTES = 1_000_000
IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".idea"}


def read_file(path: str | Path, root: Path = PROJECT_ROOT) -> str:
    resolved = ensure_allowed_path(path, root)
    if not resolved.is_file():
        raise SafetyError(f"not a file: {path}")
    if resolved.stat().st_size > MAX_FILE_BYTES:
        raise SafetyError(f"file is larger than {MAX_FILE_BYTES} bytes: {path}")
    return resolved.read_text()


def write_file(path: str | Path, content: str, root: Path = PROJECT_ROOT) -> Path:
    """Write text below games/, templates/ or generated/. Returns the resolved path."""
    resolved = ensure_writable(path, root)
    if len(content.encode()) > MAX_FILE_BYTES:
        raise SafetyError(f"content is larger than {MAX_FILE_BYTES} bytes: {path}")
    if resolved.is_dir():
        raise SafetyError(f"path is a directory: {path}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content)
    return resolved


def list_files(path: str | Path = ".", root: Path = PROJECT_ROOT, recursive: bool = False) -> list[str]:
    """Paths relative to `root`, sorted; directories end with '/'. Hides ignored and protected entries."""
    base = ensure_allowed_path(path, root)
    if not base.is_dir():
        raise SafetyError(f"not a directory: {path}")
    root = Path(root).resolve()
    entries = base.rglob("*") if recursive else base.iterdir()
    result = []
    for entry in entries:
        rel = entry.relative_to(root)
        if not entry.resolve().is_relative_to(root):  # symlink pointing outside the project
            continue
        if IGNORED_DIRS & set(rel.parts) or is_protected(entry, root):
            continue
        result.append(rel.as_posix() + ("/" if entry.is_dir() else ""))
    return sorted(result)


PROJECT_SOURCE_SUFFIXES = (".ts", ".js", ".html", ".json", ".css")
PROJECT_SKIP = ("node_modules/", "dist/", "package-lock.json", "test-results/", "playwright-report/",
                ".factory/")  # .factory/state.json: saved graph state for the human gate (M18), not game source


def read_project(project_dir: str | Path, root: Path = PROJECT_ROOT) -> dict[str, str]:
    """Source files of a generated game project, read-only: {path relative to project_dir: text}.

    Skips node_modules, dist, test reports, the lock file and .factory/ (saved graph state). Used to give nodes the project as context.
    """
    prefix = Path(project_dir).as_posix().rstrip("/") + "/"
    files = {}
    for rel in list_files(project_dir, root=root, recursive=True):
        if rel.endswith("/") or not rel.endswith(PROJECT_SOURCE_SUFFIXES) or any(s in rel for s in PROJECT_SKIP):
            continue
        files[rel.removeprefix(prefix)] = read_file(rel, root)
    return files


SNAPSHOT_SKIP_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", ".idea", "dist"})


def file_hashes(root: Path = PROJECT_ROOT, skip_dirs: frozenset[str] = SNAPSHOT_SKIP_DIRS) -> dict[str, str]:
    """sha256 of every file under `root` (relative posix path -> hash). Read-only.

    Used by dry-run runners to prove that nothing was written.
    """
    root = Path(root).resolve()
    hashes = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]  # prune: never descend into skipped dirs
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_file():
                hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes
