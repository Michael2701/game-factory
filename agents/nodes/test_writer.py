"""Test writer node, dry run (M11): GameSpec (+ project files) -> proposed Playwright tests.

Never writes files: returns a FileChangeSet with `tests/game.spec.ts` (and optionally a
new `playwright.config.ts`) for the applier. Tests are executed code, so `check_tests`
statically rejects non-deterministic or unsafe test code. Reference: docs/NODES.md.
"""

import re

from agents.llm import invoke_structured, make_llm
from agents.prompts import format_files, render_prompt
from agents.schemas import FactoryStatus, FileChangeSet, GameFactoryState, GameSpec, NodeError

NODE = "test_writer"

TEST_FILE = "tests/game.spec.ts"
CONFIG_FILE = "playwright.config.ts"
MIN_TESTS = 3

IMPORT_FROM = re.compile(r"""\bfrom\s+['"]([^'"]+)['"]|\bimport\s+['"]([^'"]+)['"]""")
TEST_CALL = re.compile(r"\btest\s*\(\s*['\"`]")
HOOK_USE = re.compile(r"__(GAME_STATE|TEST_API)__\??\.(\w+)")
WORD = re.compile(r"\w+")
GOTO = re.compile(r"""\bpage\.goto\(\s*(['"`])([^'"`]*)\1""")
# A scene switch (this.scene.start) takes effect on the next frame, so an immediate read is racy (M20).
SCENE_READ = re.compile(r"expect\(\s*await\s+page\.evaluate\([^;]*?__GAME_STATE__\??\.scene\b")
FORBIDDEN = {
    "waitForTimeout": "fixed delays are not deterministic; wait with page.waitForFunction on __GAME_STATE__",
    "setTimeout": "timers are not deterministic; wait with page.waitForFunction on __GAME_STATE__",
    "Math.random": "randomness is not deterministic; use __TEST_API__ to place objects",
    "sleep(": "sleeps are not deterministic; wait with page.waitForFunction on __GAME_STATE__",
    "require(": "only `import ... from '@playwright/test'` is allowed",
    "child_process": "tests must not run processes",
}


def check_tests(changes: FileChangeSet, spec: GameSpec, project_files: dict[str, str]) -> list[str]:
    """Static rules for proposed test files. Returns error strings (empty = ok)."""
    errors = []
    by_path = {}
    for i, change in enumerate(changes.changes):
        where = f"changes.{i} ({change.path})"
        if change.path not in (TEST_FILE, CONFIG_FILE):
            errors.append(f"{where}: only '{TEST_FILE}' (and a new '{CONFIG_FILE}') may be written")
            continue
        if change.path in by_path:
            errors.append(f"{where}: duplicate change for '{change.path}'")
            continue
        by_path[change.path] = change
        exists = change.path in project_files
        if change.operation == "delete":
            errors.append(f"{where}: delete is not allowed")
            continue
        if change.path == CONFIG_FILE and exists:
            errors.append(f"{where}: '{CONFIG_FILE}' already exists; do not change it")
        if change.operation == "create" and exists:
            errors.append(f"{where}: file already exists, use operation 'update'")
        if change.operation == "update" and not exists:
            errors.append(f"{where}: file does not exist yet, use operation 'create'")
        if not (change.content or "").strip():
            errors.append(f"{where}: content must not be empty")
        elif "```" in change.content:
            errors.append(f"{where}: content must be raw file text without markdown code fences")

    test = by_path.get(TEST_FILE)
    if test is None:
        errors.append(f"changes: must contain '{TEST_FILE}'")
        return errors
    code = test.content or ""
    where = TEST_FILE

    modules = {a or b for a, b in IMPORT_FROM.findall(code)}
    if "@playwright/test" not in modules:
        errors.append(f"{where}: must import {{ test, expect }} from '@playwright/test'")
    for module in sorted(modules - {"@playwright/test"}):
        errors.append(f"{where}: import from '{module}' is not allowed; only '@playwright/test'")
    for token, why in FORBIDDEN.items():
        if token in code:
            errors.append(f"{where}: '{token}' is not allowed ({why})")

    count = len(TEST_CALL.findall(code))
    if count < MIN_TESTS:
        errors.append(f"{where}: needs at least {MIN_TESTS} test(...) cases (loads, win, lose), got {count}")
    urls = [url for _, url in GOTO.findall(code)]
    if not urls:
        errors.append(f"{where}: tests must load the game with page.goto('/')")
    for url in sorted({u for u in urls if u != "/"}):
        errors.append(f"{where}: page.goto('{url}') is not allowed; use page.goto('/')")
    if SCENE_READ.search(code):
        errors.append(f"{where}: scene changes take effect on the next frame; check scenes only with "
                      "await page.waitForFunction(() => (window as any).__GAME_STATE__.scene === '<Scene>'), "
                      "never expect(await page.evaluate(... __GAME_STATE__.scene ...))")
    if "__GAME_STATE__" not in code:
        errors.append(f"{where}: tests must read game state through window.__GAME_STATE__")
    if any("__TEST_API__" in r for r in spec.test_requirements) and "__TEST_API__" not in code:
        errors.append(f"{where}: the GameSpec test_requirements use window.__TEST_API__; the tests must use it too")

    # Hooks are defined by game code; existing tests (e.g. the template's smoke tests, M19) only use them.
    hook_files = {p: c for p, c in project_files.items()
                  if not p.startswith("tests/") and ("__TEST_API__" in c or "__GAME_STATE__" in c)}
    if hook_files:
        defined = {w for content in hook_files.values() for w in WORD.findall(content)}
        used = sorted({f"__{obj}__.{name}" for obj, name in HOOK_USE.findall(code) if name not in defined})
        if used:
            # The repair call sees only its own output and these errors, so show what IS available.
            available = "\n".join(f"--- {p} ---\n{c.rstrip()}" for p, c in sorted(hook_files.items()))
            errors.append(f"{where}: {used} are not defined by the project's test hooks ({sorted(hook_files)}); "
                          "change only the test code: rewrite (or drop) the tests that use them so they use only the "
                          "fields and methods defined there; keep this change's path and operation. "
                          f"Available hooks:\n{available}")
    return errors


def write_tests(spec: GameSpec, project_files: dict[str, str] | None = None, llm=None) -> FileChangeSet | NodeError:
    project_files = project_files or {}
    schema = FileChangeSet.model_json_schema()
    prompt = render_prompt("test_writer", game_spec=spec, project_files=format_files(project_files), schema=schema)
    return invoke_structured(llm or make_llm(), NODE, prompt, FileChangeSet, schema,
                             check=lambda changes: check_tests(changes, spec, project_files))


def test_writer_dry_run_node(state: GameFactoryState, llm=None) -> dict:
    """LangGraph node (M13): propose tests against the virtual project (template base, M19 + coder proposals)."""
    from agents.generators.phaser_template import project_base
    from agents.nodes.coder import merge_changes  # local import: coder imports nothing from here

    if state.game_spec is None:
        error = NodeError(node=NODE, message="state has no game_spec; run the planner first")
        return {"status": FactoryStatus.ERROR, "error": f"{NODE}: {error.model_dump_json()}"}
    project_files = merge_changes(project_base(state.template, state.game_spec.slug, state.game_spec.title),
                                  state.proposed_changes)
    result = write_tests(state.game_spec, project_files, llm=llm)
    if isinstance(result, NodeError):
        return {"status": FactoryStatus.ERROR, "error": f"{NODE}: {result.model_dump_json()}"}
    return {"proposed_test_changes": result.changes, "status": FactoryStatus.CHANGES_PROPOSED, "error": None}


test_writer_dry_run_node.__test__ = False  # not a unittest/pytest test despite the name
