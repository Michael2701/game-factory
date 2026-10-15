"""Coder node, dry run (M8): one ImplementationTask -> proposed FileChangeSet.

Never writes files: the result is only a proposal that the applier (M9) validates
and applies. Tasks that produce no files (setup/build/run_tests, or no target files)
return an empty FileChangeSet without calling the LLM. Reference: docs/NODES.md.
"""

import json
import re

from agents.generators.playtest import BASE_API, BASE_STATE, CLICK, describe, hook_contract, playtest_of, scene_members
from agents.generators.phaser_template import locked_files, spec_base
from agents.llm import invoke_structured, make_llm
from agents.prompts import format_files, render_prompt
from agents.schemas import (
    FactoryStatus,
    FileChange,
    FileChangeSet,
    GameFactoryState,
    GameSpec,
    ImplementationTask,
    NodeError,
)
from agents.tools.safety import ALLOWED_BUILD_SCRIPTS

NODE = "coder"

CODER_KINDS = {"config", "code", "test_hooks", "tests"}

# Hooks every game exposes (template src/testHooks.ts); a game adds what its playtest needs (M21c:
# agents.generators.playtest.hook_contract, e.g. player / score / difficulty / clickTarget).
HOOK_CONTRACT = ("__GAME_STATE__", "__TEST_API__", *BASE_STATE, *BASE_API)

START_SCENE = "src/scenes/StartScene.ts"
# Names DEFINED in hook code: getters/methods `name(...) {` and properties `name:` (M21: a bare word such as
# `gameScene()?.result` used to satisfy the contract although __GAME_STATE__ had no `result`).
HOOK_PROPERTY = re.compile(r"\b(\w+)\s*(?:\([^)]*\)\s*(?::\s*[\w<>|' \[\]]+)?\s*\{|:)")


def hook_properties(code: str) -> set[str]:
    return set(HOOK_PROPERTY.findall(code))

# Phaser 3.90's ESM build has no default export: `import Phaser from 'phaser'` breaks the build (M14).
PHASER_DEFAULT_IMPORT = re.compile(r"""\bimport\s+Phaser\s*(?:,[^;]*?)?\s+from\s+['"]phaser['"]""")
# Pre-3.16 key event names / listeners on the InputPlugin never fire in Phaser 3.90: nobody can move (M20 runs).
PHASER2_KEY_EVENT = re.compile(r"""input\.on\(\s*['"]key(?:down|up)|['"]key(?:down|up)_[A-Z]""")
# Invented clock APIs from real runs (M21b): r10 `this.time.add(seconds)`, r11/r12 `this.time.deltaTime` (NaN).
PHASER_FAKE_CLOCK = re.compile(r"\bthis\.time\.(?:deltaTime\b|delta\b|add\s*\()")
# r13: an Arcade body has no events (`block.body.on('worldbounds', ...)` throws inside the spawn timer and
# stops the game loop), and `group.add(x)` on a physics group resets x's velocity to the group defaults (0).
BODY_EVENTS = re.compile(r"\.body(?:\s+as\s+[\w.]+)?\)?\s*\.\s*(?:on|once)\(")
BODY_VELOCITY = re.compile(r"\b(\w+)\.body(?:\s+as\s+[\w.]+)?\)?\s*\.\s*setVelocity\w*\(")
GROUP_ADD = re.compile(r"\.add\(\s*(\w+)\s*[,)]")
PHYSICS_GROUP = re.compile(r"physics\.add\.group\(")
# M21c (clicker-1, M21b r10): helpers of src/ui.ts used without importing them -> ReferenceError at runtime.
UI_EXPORTS = ("PALETTE", "title", "hint", "hud", "flash", "shake")
UI_IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*['\"]\.\.?/ui['\"]")
GAME_SCENE = "src/scenes/GameScene.ts"
KEYBOARD_INPUT = re.compile(r"createCursorKeys\(|keyboard\s*[!?]?\.\s*(?:on|once|addKey|addKeys)\(")
METHOD_DEF = re.compile(r"^[ \t]+(?:(?:private|public|protected)\s+)?(\w+)\s*\([^)]*\)\s*(?::[^{\n]+)?\{", re.M)
LIFECYCLE = {"constructor", "init", "preload", "create", "update"}  # called by Phaser itself
LOSE_CALL = re.compile(r"""endGame\(\s*['"]lose['"]""")
TEXTURE_USE = re.compile(r"""\b(?:physics\.)?add\.(?:sprite|image)\(\s*[^,()]+,\s*[^,()]+,\s*['"]([\w-]+)['"]""")
TEXTURE_DEF = re.compile(r"""\b(?:load\.(?:image|spritesheet|atlas|svg)|generateTexture|textures\.(?:create\w*|add\w*))"""
                         r"""\(\s*['"]([\w-]+)['"]""")


def phaser_problems(where: str, content: str, project_code: str, file_code: str | None = None) -> list[str]:
    """Phaser 3 pitfalls seen in real runs. `project_code`: all project code after the change."""
    errors = []
    if PHASER_DEFAULT_IMPORT.search(content):
        errors.append(f"{where}: `import Phaser from 'phaser'` breaks the build (Phaser 3.90 has no default "
                      "export); use `import * as Phaser from 'phaser'`")
    if PHASER2_KEY_EVENT.search(content):
        errors.append(f"{where}: old key event names ('keydown_LEFT', renamed in Phaser 3.16) or listeners on "
                      "this.input instead of this.input.keyboard never fire in Phaser 3.90 (the player cannot move); use "
                      "`const cursors = this.input.keyboard!.createCursorKeys()` and read `cursors.left.isDown` in "
                      "update(), or `this.input.keyboard!.on('keydown-LEFT', ...)`")
    if PHASER_FAKE_CLOCK.search(content):
        errors.append(f"{where}: Phaser's clock has no `this.time.deltaTime` / `this.time.delta` / `this.time.add()` "
                      "(they are undefined: NaN or a TypeError). The elapsed milliseconds are the second argument "
                      "of `update(time: number, delta: number)`; keep your own counter (`this.elapsed += delta / "
                      "1000`) and advance it in skipTime(seconds) too; use this.time.addEvent(...) for timers")
    whole = file_code if file_code is not None else content  # the fixer checks only added lines (content)
    missing_ui = [n for n in unimported_ui(whole) if n in unimported_ui(content)]
    if missing_ui:
        errors.append(f"{where}: uses {missing_ui} from src/ui.ts without importing them (ReferenceError at "
                      f"runtime): add `import {{ {', '.join(missing_ui)} }} from '../ui';` (from './ui' in src/*.ts)")
    if BODY_EVENTS.search(content):
        errors.append(f"{where}: an Arcade physics body has no events: `….body.on(...)` throws a TypeError (inside a "
                      "timer it stops the whole game). Check positions in update() instead, e.g. destroy objects "
                      "that left the screen there")
    late = velocity_before_group_add(content) if PHYSICS_GROUP.search(project_code) else []
    if late:
        errors.append(f"{where}: {late} get a velocity BEFORE being added to a physics group; `group.add(x)` resets "
                      "the body to the group defaults (velocity 0), so they never move. Add to the group first, "
                      "then set the velocity (or create them with `group.create(...)`)")
    defined = set(TEXTURE_DEF.findall(project_code))
    missing = sorted({key for key in TEXTURE_USE.findall(content) if key not in defined})
    if missing:
        errors.append(f"{where}: textures {missing} are never loaded or generated, so they render as missing "
                      "images; this project has no image assets: draw shapes with this.add.rectangle(...) and "
                      "give them a body with this.physics.add.existing(shape)")
    return errors


def unimported_ui(code: str) -> list[str]:
    """ui.ts helpers the code uses (PALETTE.x, hud(...)) but neither imports nor defines itself."""
    if "export const PALETTE" in code:  # ui.ts itself
        return []
    imported = {n.strip().split(" as ")[-1] for m in UI_IMPORT.finditer(code) for n in m.group(1).split(",")}
    used = [name for name in UI_EXPORTS
            if re.search(rf"(?<![\w.]){name}\s*(?:\.|\()", code) and name not in imported
            and not re.search(rf"\b(?:function|const|let|var)\s+{name}\b|^\s*{name}\s*\([^)]*\)\s*(?::[^{{\n]*)?\{{",
                              code, re.M)]
    return used


def velocity_before_group_add(code: str) -> list[str]:
    """Names whose body gets a velocity and is only afterwards passed to `<group>.add(name)` (r13)."""
    late = []
    for match in BODY_VELOCITY.finditer(code):
        name = match.group(1)
        if name in late or name == "this":
            continue
        if any(m.group(1) == name and m.start() > match.start() for m in GROUP_ADD.finditer(code)) and not any(
                m.group(1) == name and m.start() < match.start() for m in GROUP_ADD.finditer(code)):
            late.append(name)
    return late


def unwired_lose_handlers(code: str) -> list[str]:
    """Methods that call endGame('lose') but are never called or registered anywhere (r12: a collision
    handler without `physics.add.overlap`, so the player can never lose)."""
    defs = list(METHOD_DEF.finditer(code))
    unwired = []
    for i, match in enumerate(defs):
        name = match.group(1)
        body = code[match.end():defs[i + 1].start() if i + 1 < len(defs) else len(code)]
        if name in LIFECYCLE or name == "endGame" or not LOSE_CALL.search(body):
            continue
        if len(re.findall(rf"\b{re.escape(name)}\b", code)) < 2:  # only its own definition
            unwired.append(name)
    return unwired


def sets_member(code: str, name: str) -> bool:
    """The scene code assigns or defines `name` (this.name = …, a class field, or a getter)."""
    return bool(re.search(rf"this\.{name}\s*=[^=]|^\s*(?:(?:public|private|protected|readonly)\s+)*{name}\s*[!?]?\s*[:=]"
                          rf"|\bget\s+{name}\s*\(", code, re.M))


def gameplay_problems(code: str, spec: GameSpec | None) -> list[str]:
    """Must-haves of the game scene that the tests can only catch late (M21b r12; per game since M21c)."""
    if spec is None:
        return []
    errors = []
    pt = playtest_of(spec)
    keys = sorted({i.input for i in pt.inputs if i.input != CLICK})
    if keys and not KEYBOARD_INPUT.search(code):
        errors.append(f"changes ({GAME_SCENE}): the acceptance test presses the real keys {keys}, but the game "
                      "scene reads no keyboard input: e.g. `this.input.keyboard!.addKey('SPACE')`, "
                      "`this.input.keyboard!.createCursorKeys()` (read `.isDown` in update()) or "
                      "`this.input.keyboard!.on('keydown-SPACE', ...)`")
    for name, what in scene_members(pt).items():
        if not sets_member(code, name):
            errors.append(f"changes ({GAME_SCENE}): the tests read `{name}` — {what} — but the game scene never "
                          f"sets it")
    for name in unwired_lose_handlers(code):
        errors.append(f"changes ({GAME_SCENE}): {name}() ends the game with 'lose' but is never called or "
                      f"registered, so the player can never lose; register it in create() (a physics "
                      f"overlap/collider, an input handler or a timer that calls this.{name}())")
    return errors


def is_coder_task(task: ImplementationTask) -> bool:
    return task.kind in CODER_KINDS and bool(task.target_files)


def check_changes(
    changes: FileChangeSet,
    task: ImplementationTask,
    existing_files: dict[str, str],
    optional_paths: list[str] | tuple[str, ...] = (),
    locked_paths: list[str] | tuple[str, ...] = (),
    spec: GameSpec | None = None,
) -> list[str]:
    """Semantic rules for proposed changes. Returns error strings (empty = ok).

    Every target file must be changed; `optional_paths` (existing integration files such as
    src/main.ts) may additionally be updated, never created. `locked_paths` (template config,
    M19) may never be changed.
    """
    errors = []
    after = merge_changes(existing_files, changes.changes)
    project_code = "\n".join(c for p, c in after.items() if p.endswith(".ts"))
    optional = set(optional_paths) - set(task.target_files)
    allowed = set(task.target_files) | optional
    paths = [c.path for c in changes.changes]
    if not paths:
        errors.append(f"changes: must contain one change for each allowed path {task.target_files}")
    for path in sorted({p for p in paths if paths.count(p) > 1}):
        errors.append(f"changes: duplicate change for '{path}'")
    for path in sorted(set(task.target_files) - set(paths)):
        if paths:
            errors.append(f"changes: missing a change for allowed path '{path}'")

    for i, change in enumerate(changes.changes):
        where = f"changes.{i} ({change.path})"
        if change.path in locked_paths:
            errors.append(f"{where}: '{change.path}' is a locked template file (pinned versions / config); "
                          "do not change it")
            continue
        if change.path not in allowed:
            errors.append(f"{where}: path is not allowed; allowed paths are {sorted(allowed)}")
            continue
        exists = change.path in existing_files
        if change.path in optional and change.operation != "update":
            errors.append(f"{where}: optional integration files may only be updated")
            continue
        if change.operation == "delete":
            errors.append(f"{where}: delete is not allowed")
            continue
        if change.operation == "create" and exists:
            errors.append(f"{where}: file already exists, use operation 'update'")
        if change.operation == "update" and not exists:
            errors.append(f"{where}: file does not exist yet, use operation 'create'")
        content = change.content if change.content is not None else change.patch
        if not content or not content.strip():
            errors.append(f"{where}: content must not be empty")
            continue
        if "```" in content:
            errors.append(f"{where}: content must be raw file text without markdown code fences")
        if change.path.endswith(".ts"):
            errors += phaser_problems(where, content, project_code)
        if change.path == START_SCENE and "pointerdown" not in content:  # M21 acceptance: click to start
            errors.append(f"{where}: the start screen must start the game on a click anywhere: keep "
                          "this.input.once('pointerdown', () => this.scene.start('GameScene'))")
        if change.path.endswith(".json") and change.content is not None:
            try:
                data = json.loads(change.content)
            except json.JSONDecodeError as exc:
                errors.append(f"{where}: invalid JSON ({exc.msg} at line {exc.lineno})")
                continue
            if change.path.split("/")[-1] == "package.json":
                build = data.get("scripts", {}).get("build") if isinstance(data, dict) else None
                if build not in ALLOWED_BUILD_SCRIPTS:
                    errors.append(f"{where}: scripts.build must be one of {list(ALLOWED_BUILD_SCRIPTS)}, got {build!r}")

    game_scene = next((c.content for c in changes.changes if c.path == GAME_SCENE and c.content), None)
    if game_scene is not None:
        errors += gameplay_problems(game_scene, spec)

    if task.kind == "test_hooks" and changes.changes:
        code = "\n".join(c.content or "" for c in changes.changes)
        defined = hook_properties(code)
        contract = hook_contract(spec) if spec is not None else HOOK_CONTRACT
        missing = [name for name in contract
                   if not (name in defined if not name.startswith("__") else re.search(rf"\b{name}\b", code))]
        if missing:
            errors.append(f"changes: test hooks must expose the hook contract; missing {missing} "
                          "(keep every getter and method of the template's src/testHooks.ts and add the game's own "
                          "values from test_requirements)")
    return errors


def code_task(
    task: ImplementationTask,
    spec: GameSpec,
    existing_files: dict[str, str] | None = None,
    llm=None,
    optional_paths: list[str] | None = None,
    locked_paths: list[str] | tuple[str, ...] = (),
) -> FileChangeSet | NodeError:
    existing_files = existing_files or {}
    if not is_coder_task(task):
        return FileChangeSet(changes=[])
    optional = [p for p in (optional_paths or []) if p in existing_files and p not in task.target_files]

    schema = FileChangeSet.model_json_schema()
    # All existing files are shown as context (e.g. scene class names imported by main.ts).
    prompt = render_prompt(
        "coder",
        task=task,
        game_spec=spec,
        allowed_paths=task.target_files,
        optional_paths=optional or "(none)",
        locked_paths=list(locked_paths) or "(none)",
        existing_files=format_files(existing_files),
        playtest=describe(spec),
        schema=schema,
    )
    return invoke_structured(llm or make_llm(), NODE, prompt, FileChangeSet, schema,
                             check=lambda changes: check_changes(changes, task, existing_files, optional,
                                                                 locked_paths, spec))


# --- graph integration (M13) -------------------------------------------------

INTEGRATION_FILES = ("src/main.ts",)  # later tasks may update these to wire in their work
GRAPH_CODER_KINDS = CODER_KINDS - {"tests"}  # 'tests' tasks belong to the test writer node


def merge_changes(files: dict[str, str], changes: list[FileChange]) -> dict[str, str]:
    """Apply proposed changes to a virtual file system {path: content} (no disk access)."""
    merged = dict(files)
    for change in changes:
        if change.operation == "delete":
            merged.pop(change.path, None)
        elif change.content is not None:
            merged[change.path] = change.content
    return merged


def coder_dry_run_node(state: GameFactoryState, llm=None) -> dict:
    """LangGraph node: code every coder task in plan order against a virtual file system.

    Each task sees the project base (the instantiated template, M19) plus all files proposed
    by earlier tasks and may update integration files (src/main.ts). Stops at the first
    NodeError, keeping the proposals made so far. Proposals never include the base files.
    """
    if state.game_spec is None or state.task_plan is None:
        error = NodeError(node=NODE, message="state needs game_spec and task_plan; run planner and decomposer first")
        return {"status": FactoryStatus.ERROR, "error": f"{NODE}: {error.model_dump_json()}"}

    proposed: list[FileChange] = list(state.proposed_changes)
    base = spec_base(state.template, state.game_spec)
    locked = locked_files(state.template)
    files = merge_changes(base, proposed)
    for task in state.task_plan.tasks:
        if task.kind not in GRAPH_CODER_KINDS or not task.target_files:
            continue
        result = code_task(task, state.game_spec, existing_files=files, llm=llm,
                           optional_paths=list(INTEGRATION_FILES), locked_paths=locked)
        if isinstance(result, NodeError):
            result = result.model_copy(update={"message": f"task {task.id}: {result.message}"})
            return {"proposed_changes": proposed, "status": FactoryStatus.ERROR,
                    "error": f"{NODE}: {result.model_dump_json()}"}
        proposed += result.changes
        files = merge_changes(files, result.changes)
    return {"proposed_changes": proposed, "status": FactoryStatus.CODING, "error": None}
