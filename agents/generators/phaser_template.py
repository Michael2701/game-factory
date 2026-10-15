"""Phaser + Vite + TypeScript template as the agents' output target (M19).

The template lives in `templates/phaser-vite-template/` (static files, not a game). Every
generated project starts from `instantiate(...)`: the template files with the package name
and page title filled in. The coder and test writer see these files as existing (so they
update them), the applier writes template + proposals, and LOCKED_FILES (pinned versions,
build/test config) may not be planned or changed by the decomposer and the coder.
Reference: docs/GENERATORS.md.
"""

import html
import json
from pathlib import Path

from agents.schemas import FileChange
from agents.tools.filesystem import list_files, read_file
from agents.tools.safety import PROJECT_ROOT

TEMPLATES_DIR = "templates"
DEFAULT_TEMPLATE = "phaser-vite-template"
LOCKED_FILES = ("package.json", "index.html", "tsconfig.json", "playwright.config.ts",
                "vite.config.ts", "tests/fixtures.ts", "tests/acceptance.spec.ts")  # last three: M21
TEMPLATE_ONLY = ("README.md",)  # documents the template; not copied into projects
TEMPLATE_TITLE = "<title>Phaser Vite Template</title>"
TITLE_MARK, HINT_MARK = "__GAME_TITLE__", "__CONTROLS_HINT__"  # in src/scenes/StartScene.ts (M22)
DEFAULT_HINT = "Use the keyboard to play"
KEY_GLYPHS = {"arrowleft": "←", "arrowright": "→", "arrowup": "↑", "arrowdown": "↓", "space": "Space"}


def controls_hint(spec) -> str:
    """One readable line for the start screen, e.g. '← move left · → move right'."""
    parts = [f"{KEY_GLYPHS.get(c.input.lower().replace(' ', ''), c.input)} {c.action}" for c in spec.controls]
    return " · ".join(parts)[:60] or DEFAULT_HINT


def _ts_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")

# Shown to the task decomposer (prompt variable `project_base`); every template file is described.
TEMPLATE_GUIDE = """The project starts from the Phaser + Vite template. These files ALREADY EXIST:
- package.json, index.html, tsconfig.json, playwright.config.ts, vite.config.ts, tests/fixtures.ts (browser errors fail tests) and tests/acceptance.spec.ts (written by the factory from the GameSpec playtest: real clicks and key presses): LOCKED. Never put them in target_files.
- src/main.ts: boots Phaser (480x640) with Arcade Physics enabled (this.physics works in every scene) and the scenes [StartScene, GameScene, GameOverScene], and calls setupTestHooks(game). Scene tasks update it to register new scenes.
- src/scenes/StartScene.ts: finished start screen (game title, controls line, click to start). Plan a task for it only if the game needs more.
- src/scenes/GameScene.ts: placeholder with a HUD text (hudText), endGame(result) and skipTime(seconds). Plan a task that updates it with the game described in the GameSpec.
- src/scenes/GameOverScene.ts: finished result screen (win/lose message, click to play again). Update it only if the game needs more (e.g. the final score).
- src/ui.ts: look helpers (PALETTE, title, hint, hud, flash, shake) for every scene.
- src/testHooks.ts: generic hook contract (window.__GAME_STATE__ scene/result/player/score/difficulty/clickTarget/texts/objects read from GameScene members, window.__TEST_API__ startGame()/skipTime()/finishRound()). The test_hooks task adds the game's own values from test_requirements.
- tests/game.spec.ts: template smoke tests. The tests task replaces it.
Plan, in this order: Phaser scene files (src/scenes/), test hooks (src/testHooks.ts), Playwright tests (tests/game.spec.ts), build, run tests. No setup or config tasks: the structure and package.json are done."""

EMPTY_GUIDE = """The project starts EMPTY.
Cover, in this order: project structure, package.json, Vite entry point (index.html, src/main.ts), Phaser scene files (src/scenes/), test hooks (`window.__GAME_STATE__`, `window.__TEST_API__`), Playwright tests (tests/game.spec.ts), build, run tests."""


def template_dir(name: str = DEFAULT_TEMPLATE) -> str:
    return f"{TEMPLATES_DIR}/{name}"


def template_files(name: str = DEFAULT_TEMPLATE, root: Path = PROJECT_ROOT) -> dict[str, str]:
    """{path relative to the template: text}, read through the safe tools (always from the repo)."""
    base = template_dir(name)
    prefix = base + "/"
    return {rel.removeprefix(prefix): read_file(rel, root)
            for rel in list_files(base, root=root, recursive=True)
            if not rel.endswith("/") and rel.removeprefix(prefix) not in TEMPLATE_ONLY}


def instantiate(slug: str, title: str, name: str = DEFAULT_TEMPLATE, root: Path = PROJECT_ROOT,
                hint: str = DEFAULT_HINT) -> dict[str, str]:
    """Template files for one game: package.json name = slug, page <title> and start-screen title = title,
    start-screen controls line = hint (M22)."""
    files = template_files(name, root)
    package = json.loads(files["package.json"])
    package["name"] = slug
    files["package.json"] = json.dumps(package, indent=2) + "\n"
    files["index.html"] = files["index.html"].replace(TEMPLATE_TITLE, f"<title>{html.escape(title)}</title>")
    start = "src/scenes/StartScene.ts"
    if start in files:
        files[start] = files[start].replace(TITLE_MARK, _ts_string(title)).replace(HINT_MARK, _ts_string(hint))
    return files


def template_changes(slug: str, title: str, name: str = DEFAULT_TEMPLATE) -> list[FileChange]:
    return [FileChange(path=path, operation="create", content=content, reason=f"template {name}")
            for path, content in instantiate(slug, title, name).items()]


def project_base(template: str | None, slug: str, title: str, hint: str = DEFAULT_HINT) -> dict[str, str]:
    """Starting files of a generated project: the instantiated template, or {} without one."""
    return instantiate(slug, title, template, hint=hint) if template else {}


def spec_base(template: str | None, spec) -> dict[str, str]:
    """project_base for a GameSpec: slug, title and the controls hint come from the spec."""
    return project_base(template, spec.slug, spec.title, controls_hint(spec))


def locked_files(template: str | None) -> tuple[str, ...]:
    return LOCKED_FILES if template else ()


def guide(template: str | None) -> str:
    return TEMPLATE_GUIDE if template else EMPTY_GUIDE
