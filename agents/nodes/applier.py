"""Applier nodes: write the proposed project (M14) and apply fixes inside it (M16).

Only reached when the graph is built with `apply=True` (`--apply`). The coder proposes a
chain of create/update changes per file; they are merged into the final virtual project
and written as one `create` per file into a NEW (or empty) folder below `generated/` or
`games/`. Validation is all-or-nothing through `apply_changes`: preview first, then write.
Existing folders are never overwritten.

`apply_fix_node` (fix loop) is the only writer into an EXISTING project: it applies the
fixer's `state.fix_changes` inside `state.target_dir` (below generated/ or games/), again
preview first, all-or-nothing. Reference: docs/NODES.md, docs/TOOLS.md.
"""

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from agents.generators.acceptance import ACCEPTANCE_FILE, acceptance_spec
from agents.generators.phaser_template import spec_base
from agents.nodes.coder import merge_changes
from agents.schemas import FactoryStatus, FileChange, GameFactoryState, NodeError
from agents.tools.apply_changes import apply_changes
from agents.tools.filesystem import read_project, write_file
from agents.tools.safety import PROJECT_ROOT, SafetyError, ensure_writable

NODE = "applier"
FIX_NODE = "apply_fix"

APPLY_ROOTS = ("generated", "games")  # templates/ is a write root, but not a target for generated games
TARGET_REFUSED = "target refused"  # error prefix; the CLI maps it to exit code 2


def default_target(slug: str) -> str:
    return f"generated/{slug}"


def check_target(target_dir: str | Path, root: Path = PROJECT_ROOT) -> str:
    """Require a new or empty folder below generated/ or games/. Returns it project-relative."""
    root = Path(root).resolve()
    resolved = ensure_writable(target_dir, root)
    rel = resolved.relative_to(root)
    if rel.parts[0] not in APPLY_ROOTS:
        raise SafetyError(f"target must be a folder below {list(APPLY_ROOTS)}: {target_dir}")
    if resolved.exists() and not resolved.is_dir():
        raise SafetyError(f"target is not a directory: {target_dir}")
    if resolved.is_dir() and any(resolved.iterdir()):
        raise SafetyError(f"target already exists and is not empty (nothing is overwritten): {rel.as_posix()}")
    return rel.as_posix()


MANIFEST_FILE = ".factory/manifest.json"


def source_hashes(target: str, root: Path = PROJECT_ROOT) -> dict[str, str]:
    """sha256 of every source file of the project (read_project view: no node_modules/dist/.factory)."""
    return {p: hashlib.sha256(c.encode()).hexdigest() for p, c in sorted(read_project(target, root).items())}


def write_manifest(target: str, by: str, root: Path = PROJECT_ROOT) -> None:
    """Record the project's sources right after an agent write (M21: proves no manual edits later)."""
    data = {"written_by": by, "files": source_hashes(target, root)}
    write_file(f"{target}/{MANIFEST_FILE}", json.dumps(data, indent=2) + "\n", root)


def final_changes(state: GameFactoryState) -> list[FileChange]:
    """Merge the project base (template, M19), then all proposals (code, then tests) into one `create` per file."""
    base = spec_base(state.template, state.game_spec) if state.game_spec else {}
    files = merge_changes(base, [*state.proposed_changes, *state.proposed_test_changes])
    if state.template and state.game_spec:  # M21: locked, written by code from the GameSpec, never by the LLM
        files[ACCEPTANCE_FILE] = acceptance_spec(state.game_spec, import_from="./fixtures")
    return [FileChange(path=path, operation="create", content=content, reason="final merged proposal")
            for path, content in files.items()]


def apply_node(state: GameFactoryState, root: Path = PROJECT_ROOT) -> dict:
    """LangGraph node: preview, then write the final project into `state.target_dir`."""
    if state.game_spec is None or not state.proposed_changes:
        error = NodeError(node=NODE, message="nothing to apply; run the dry-run nodes first")
        return {"status": FactoryStatus.ERROR, "error": f"{NODE}: {error.model_dump_json()}"}

    target = state.target_dir or default_target(state.game_spec.slug)
    try:
        target = check_target(target, root)
    except SafetyError as exc:
        return {"target_dir": target, "status": FactoryStatus.ERROR, "error": f"{NODE}: {TARGET_REFUSED}: {exc}"}

    try:
        changes = final_changes(state)
    except ValidationError as exc:  # a proposal that bypassed the schema (e.g. built without validation)
        return {"target_dir": target, "status": FactoryStatus.ERROR,
                "error": f"{NODE}: REJECTED · nothing written · invalid change: {exc.errors()[0]['msg']}"}
    preview = apply_changes(changes, target, root=root)
    if not preview.ok:
        return {"target_dir": target, "status": FactoryStatus.ERROR, "error": f"{NODE}: {preview.summary()}"}
    result = apply_changes(changes, target, apply=True, root=root)
    if not result.ok:
        return {"target_dir": target, "status": FactoryStatus.ERROR, "error": f"{NODE}: {result.summary()}"}
    write_manifest(target, "apply_changes", root)
    return {"target_dir": target, "changed_files": result.changed_files,
            "status": FactoryStatus.CHANGES_APPLIED, "error": None}


def check_fix_target(target_dir: str | None, root: Path = PROJECT_ROOT) -> str:
    """Require an existing project folder below generated/ or games/. Returns it project-relative."""
    if not target_dir:
        raise SafetyError("state has no target_dir")
    root = Path(root).resolve()
    resolved = ensure_writable(target_dir, root)
    rel = resolved.relative_to(root)
    if rel.parts[0] not in APPLY_ROOTS or len(rel.parts) < 2:
        raise SafetyError(f"fix target must be a folder below {list(APPLY_ROOTS)}: {target_dir}")
    if not resolved.is_dir():
        raise SafetyError(f"fix target is not an existing project folder: {rel.as_posix()}")
    return rel.as_posix()


def apply_fix_node(state: GameFactoryState, root: Path = PROJECT_ROOT) -> dict:
    """LangGraph node: preview, then apply `state.fix_changes` inside `state.target_dir`.

    On success the fix is consumed (`fix_changes` cleared) and the written paths are added
    to `changed_files`; on any rejection nothing is written and the loop ends with an error.
    """
    def error(message: str) -> dict:
        return {"status": FactoryStatus.ERROR, "error": f"{FIX_NODE}: {message}"}

    if not state.fix_changes:
        return error("no fix to apply; run the fixer first")
    try:
        target = check_fix_target(state.target_dir, root)
        changes = [FileChange.model_validate(c.model_dump()) for c in state.fix_changes]
    except SafetyError as exc:
        return error(f"target refused: {exc}")
    except ValidationError as exc:
        return error(f"REJECTED · nothing written · invalid change: {exc.errors()[0]['msg']}")
    preview = apply_changes(changes, target, root=root)
    if not preview.ok:
        return error(preview.summary())
    result = apply_changes(changes, target, apply=True, root=root)
    if not result.ok:
        return error(result.summary())
    changed = list(dict.fromkeys([*state.changed_files, *result.changed_files]))
    write_manifest(target, "apply_fix", root)
    return {"changed_files": changed, "fix_changes": [], "status": FactoryStatus.TESTING, "error": None}
