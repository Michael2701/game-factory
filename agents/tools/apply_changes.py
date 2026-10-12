"""Controlled applier for proposed FileChanges (M9).

The only place where LLM-proposed changes reach the disk. Dry run is the default;
`apply=True` writes. Validation is all-or-nothing: if any change is invalid, nothing
is written and `ApplyResult.errors` explains why.

Usage pattern (show a summary before applying):
    preview = apply_changes(change_set, "generated/block-dodger")
    print(preview.summary())
    if preview.ok:
        result = apply_changes(change_set, "generated/block-dodger", apply=True)

Reference: docs/TOOLS.md.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agents.schemas import FileChange, FileChangeSet
from agents.tools.filesystem import MAX_FILE_BYTES, write_file
from agents.tools.safety import (
    PROJECT_ROOT,
    WRITE_ROOTS,
    SafetyError,
    ensure_writable,
    package_json_problems,
)


class PlannedChange(BaseModel):
    path: str  # project-relative
    operation: Literal["create", "update", "delete"]
    bytes: int = 0
    old_bytes: int | None = None


class ApplyResult(BaseModel):
    target_dir: str
    dry_run: bool
    planned: list[PlannedChange] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)  # project-relative; empty in dry run
    errors: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        mode = "DRY RUN" if self.dry_run else "APPLIED"
        lines = [f"{mode} · {self.target_dir} · {len(self.planned)} change(s)"]
        if self.errors:
            lines[0] = f"REJECTED · {self.target_dir} · nothing written"
            lines += [f"  ERROR  {e}" for e in self.errors]
            return "\n".join(lines)
        width = max((len(p.path) for p in self.planned), default=0)
        for p in self.planned:
            size = f"{p.bytes} B" if p.operation != "delete" else ""
            was = f" (was {p.old_bytes} B)" if p.old_bytes is not None and p.operation == "update" else ""
            lines.append(f"  {p.operation.upper():<6}  {p.path:<{width}}  {size}{was}")
        return "\n".join(lines)


def _target_dir(target_dir: str | Path, root: Path) -> Path:
    resolved = ensure_writable(target_dir, root)  # inside a write root, at least one level down
    rel = resolved.relative_to(Path(root).resolve())
    if rel.parts[0] not in WRITE_ROOTS or len(rel.parts) < 2:
        raise SafetyError(f"target_dir must be a folder below {list(WRITE_ROOTS)}: {target_dir}")
    if resolved.exists() and not resolved.is_dir():
        raise SafetyError(f"target_dir is not a directory: {target_dir}")
    return resolved


def _validate(change: FileChange, target: Path, root: Path) -> tuple[Path | None, list[str]]:
    errors = []
    try:
        path = ensure_writable(target / change.path, root)
    except SafetyError as exc:
        return None, [f"{change.path}: {exc}"]
    if not path.is_relative_to(target):
        return None, [f"{change.path}: resolves outside the target folder"]
    if path.is_dir():
        return None, [f"{change.path}: is a directory"]

    exists = path.is_file()
    if change.operation == "create" and exists:
        errors.append(f"{change.path}: create, but the file already exists (use update)")
    if change.operation in ("update", "delete") and not exists:
        errors.append(f"{change.path}: {change.operation}, but the file does not exist")
    if change.patch is not None:
        errors.append(f"{change.path}: patch is not supported; send the full file content")
    if change.content is not None:
        if len(change.content.encode()) > MAX_FILE_BYTES:
            errors.append(f"{change.path}: content is larger than {MAX_FILE_BYTES} bytes")
        if path.name == "package.json":
            errors += [f"{change.path}: {p}" for p in package_json_problems(change.content)]
    return path, errors


def apply_changes(
    changes: FileChangeSet | list[FileChange],
    target_dir: str | Path,
    *,
    apply: bool = False,
    root: Path = PROJECT_ROOT,
) -> ApplyResult:
    """Validate all changes; write them only when `apply=True` and everything is valid."""
    items = changes.changes if isinstance(changes, FileChangeSet) else list(changes)
    root = Path(root).resolve()
    result = ApplyResult(target_dir=str(target_dir), dry_run=not apply)
    try:
        target = _target_dir(target_dir, root)
    except SafetyError as exc:
        result.errors.append(str(exc))
        return result
    result.target_dir = target.relative_to(root).as_posix()

    validated: list[tuple[FileChange, Path]] = []
    seen: set[Path] = set()
    for change in items:
        path, errors = _validate(change, target, root)
        if path is not None and path in seen:
            errors.append(f"{change.path}: duplicate change for the same file")
        result.errors += errors
        if path is None:
            continue
        seen.add(path)
        validated.append((change, path))
        result.planned.append(PlannedChange(
            path=path.relative_to(root).as_posix(),
            operation=change.operation,
            bytes=len(change.content.encode()) if change.content is not None else 0,
            old_bytes=path.stat().st_size if path.is_file() else None,
        ))

    if result.errors or not apply:  # an empty change set is a valid no-op
        return result

    for change, path in validated:
        rel = path.relative_to(root).as_posix()
        if change.operation == "delete":
            path.unlink()
        else:
            write_file(rel, change.content, root)
        result.changed_files.append(rel)
    return result
