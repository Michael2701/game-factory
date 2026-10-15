"""M19 Phaser + Vite template: files, instantiation, locks, use by the agents, scripts/new_from_template.py.

Gated (RUN_NPM_TESTS=1): a project created from the template really installs, builds and
passes its 3 Playwright smoke tests.
"""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agents.generators.phaser_template import (  # noqa: E402
    DEFAULT_TEMPLATE,
    LOCKED_FILES,
    TEMPLATE_GUIDE,
    instantiate,
    project_base,
    template_changes,
    template_dir,
    template_files,
)
from agents.nodes import test_runner  # noqa: E402
from agents.nodes.applier import final_changes  # noqa: E402
from agents.nodes.coder import HOOK_CONTRACT, check_changes  # noqa: E402
from agents.nodes.task_decomposer import check_plan  # noqa: E402
from agents.nodes.test_writer import check_tests  # noqa: E402
from agents.schemas import FileChange, FileChangeSet, GameFactoryState, TaskPlan, TestResult  # noqa: E402
from agents.schemas.examples import sample_game_spec, sample_task_plan, sample_template_task_plan  # noqa: E402
from scripts import new_from_template  # noqa: E402

PINS = {"phaser": "3.90.0", "vite": "8.3.1", "typescript": "6.0.3", "@playwright/test": "1.62.0"}
EXPECTED_FILES = ["index.html", "package.json", "playwright.config.ts", "src/main.ts", "src/scenes/GameOverScene.ts",
                  "src/scenes/GameScene.ts",
                  "src/scenes/StartScene.ts", "src/testHooks.ts", "src/ui.ts", "tests/fixtures.ts", "tests/game.spec.ts",
                  "tsconfig.json", "vite.config.ts"]
SPEC = sample_game_spec()


def change_set(*items) -> FileChangeSet:
    return FileChangeSet(changes=[FileChange(path=p, operation=op, content=c, reason="r") for p, op, c in items])


class TemplateFilesTest(unittest.TestCase):
    def setUp(self):
        self.files = template_files()

    def test_layout(self):
        self.assertEqual(sorted(self.files), EXPECTED_FILES)
        self.assertTrue((ROOT / template_dir() / "README.md").is_file())  # documented, not copied

    def test_package_json_pins_and_scripts(self):
        package = json.loads(self.files["package.json"])
        deps = {**package["dependencies"], **package["devDependencies"]}
        self.assertEqual(deps, PINS)  # exact versions, nothing else
        self.assertEqual(package["scripts"]["build"], "vite build")
        self.assertEqual(package["type"], "module")

    def test_phaser_namespace_import_everywhere(self):
        for path, text in self.files.items():
            if "phaser" in text and path.endswith(".ts") and "from 'phaser'" in text:
                with self.subTest(path=path):
                    self.assertIn("import * as Phaser from 'phaser';", text)

    def test_hook_contract(self):
        hooks = self.files["src/testHooks.ts"]
        for name in HOOK_CONTRACT:
            self.assertRegex(hooks, rf"\b{name}\b")
        self.assertIn("setupTestHooks(game)", self.files["src/main.ts"])
        self.assertIn("scene: [StartScene, GameScene, GameOverScene]", self.files["src/main.ts"])
        # M19 real run: the coder used this.physics.add.* while physics was off -> every scene crashed
        self.assertIn("physics: { default: 'arcade'", self.files["src/main.ts"])

    def test_smoke_tests_pass_the_test_writer_rules(self):
        """The template's own tests satisfy the rules the test writer must follow (imports, hooks, >= 3 tests)."""
        tests = change_set(("tests/game.spec.ts", "update", self.files["tests/game.spec.ts"]))
        self.assertEqual(check_tests(tests, SPEC, self.files), [])

    def test_old_tests_are_not_a_hook_source(self):
        """M19 real run: the template's smoke tests were counted as hook definitions for the test writer."""
        files = {**self.files, "tests/game.spec.ts": self.files["tests/game.spec.ts"] + "// __GAME_STATE__.lives\n"}
        tests = self.files["tests/game.spec.ts"].replace(
            "(window as any).__GAME_STATE__.result)", "(window as any).__GAME_STATE__.lives)")
        errors = check_tests(change_set(("tests/game.spec.ts", "update", tests)), SPEC, files)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("['__GAME_STATE__.lives'] are not defined by the project's test hooks (['src/testHooks.ts'])",
                      errors[0])

    def test_guide_describes_every_file(self):
        for path in EXPECTED_FILES:
            with self.subTest(path=path):
                self.assertIn(path, TEMPLATE_GUIDE)


class InstantiateTest(unittest.TestCase):
    def test_slug_and_title(self):
        files = instantiate("my-game", "My <Game>")
        self.assertEqual(json.loads(files["package.json"])["name"], "my-game")
        self.assertIn("<title>My &lt;Game&gt;</title>", files["index.html"])
        start = files["src/scenes/StartScene.ts"]
        self.assertIn("title(this, 'My <Game>');", start)  # M22: start screen title + controls hint filled in
        self.assertIn("hint(this, 'Use the keyboard to play');", start)
        self.assertNotIn("__GAME_TITLE__", start)
        changed = ("package.json", "index.html", "src/scenes/StartScene.ts")
        self.assertEqual({k: v for k, v in files.items() if k not in changed},
                         {k: v for k, v in template_files().items() if k not in changed})

    def test_changes_and_project_base(self):
        changes = template_changes("my-game", "My Game")
        self.assertEqual(sorted(c.path for c in changes), EXPECTED_FILES)
        self.assertTrue(all(c.operation == "create" for c in changes))
        self.assertEqual(project_base(None, "x", "X"), {})
        self.assertEqual(project_base(DEFAULT_TEMPLATE, "x", "X"), instantiate("x", "X"))


class LocksTest(unittest.TestCase):
    def test_coder_rejects_locked_files(self):
        task = sample_template_task_plan().tasks[0]
        base = instantiate("block-dodger", "Block Dodger")
        bad = change_set(("src/scenes/StartScene.ts", "update", "this.input.once('pointerdown', f);\n"),
                         ("src/scenes/GameScene.ts", "update", "x\n"),
                         ("src/scenes/GameOverScene.ts", "update", "export class GameOverScene {}\n"),
                         ("package.json", "update", '{"scripts": {"build": "vite build"}}'))
        errors = check_changes(bad, task, base, ["src/main.ts"], LOCKED_FILES)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("locked template file", errors[0])

    def test_coder_rejects_phaser_default_import(self):
        task = sample_template_task_plan().tasks[0]
        for line in ["import Phaser from 'phaser';", 'import Phaser from "phaser";',
                     "import Phaser, { Scene } from 'phaser';"]:
            with self.subTest(line=line):
                changes = change_set(("src/scenes/StartScene.ts", "update", line + "\n"),
                                     ("src/scenes/GameScene.ts", "update", "x\n"),
                                     ("src/scenes/GameOverScene.ts", "update", "x\n"))
                errors = check_changes(changes, task, instantiate("b", "B"))
                self.assertTrue(any("import * as Phaser" in e for e in errors), errors)

    def test_decomposer_locks_and_kinds(self):
        self.assertEqual(check_plan(sample_template_task_plan(), SPEC, template=DEFAULT_TEMPLATE), [])
        errors = check_plan(sample_task_plan(), SPEC, template=DEFAULT_TEMPLATE)  # scratch plan writes package.json
        self.assertEqual([e.split(" is a locked")[0] for e in errors], ["T2: 'package.json'", "T3: 'index.html'"])
        # without a template a config task is still required
        self.assertTrue(any("['config']" in e for e in check_plan(sample_template_task_plan(), SPEC)))
        self.assertEqual(check_plan(sample_task_plan(), SPEC), [])

    def test_template_plan_validates(self):
        plan = sample_template_task_plan()
        self.assertEqual(TaskPlan.model_validate_json(plan.model_dump_json()), plan)


class FinalProjectTest(unittest.TestCase):
    def test_final_changes_include_template(self):
        state = GameFactoryState(user_idea="x", game_spec=SPEC, template=DEFAULT_TEMPLATE, proposed_changes=[
            FileChange(path="src/scenes/GameScene.ts", operation="update", content="game\n", reason="r"),
            FileChange(path="src/scenes/GameOverScene.ts", operation="update", content="over\n", reason="r")])
        files = {c.path: c.content for c in final_changes(state)}
        self.assertEqual(sorted(files), sorted([*EXPECTED_FILES, "tests/acceptance.spec.ts"]))  # M21: by code
        self.assertIn("page.keyboard.down('ArrowLeft')", files["tests/acceptance.spec.ts"])
        self.assertEqual(files["src/scenes/GameScene.ts"], "game\n")
        self.assertEqual(files["playwright.config.ts"], template_files()["playwright.config.ts"])
        scratch = state.model_copy(update={"template": None})
        self.assertEqual(sorted(c.path for c in final_changes(scratch)),
                         ["src/scenes/GameOverScene.ts", "src/scenes/GameScene.ts"])


def run_script(argv, root):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = new_from_template.main(["new_from_template.py", *argv], root=root)
    return code, out.getvalue()


class TempRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "generated").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def tree(self, target: str) -> list[str]:
        base = self.root / target
        return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())


class ScriptTest(TempRoot):
    def test_writes_instantiated_template(self):
        code, out = run_script(["--target", "generated/tpl-demo", "--title", "Tpl Demo"], self.root)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.tree("generated/tpl-demo"), EXPECTED_FILES)
        self.assertIn("WROTE  package.json   (locked)", out)
        package = json.loads((self.root / "generated/tpl-demo/package.json").read_text())
        self.assertEqual(package["name"], "tpl-demo")
        self.assertIn("<title>Tpl Demo</title>", (self.root / "generated/tpl-demo/index.html").read_text())

    def test_refused_targets_write_nothing(self):
        (self.root / "generated/full").mkdir()
        (self.root / "generated/full/old.txt").write_text("old")
        for bad in ["generated/full", "templates/x", "generated", "../x"]:
            with self.subTest(target=bad):
                code, out = run_script(["--target", bad], self.root)
                self.assertEqual(code, 2, out)
                self.assertIn("target refused", out)
        self.assertEqual(self.tree("generated"), ["full/old.txt"])

    def test_check_failure_exit_1(self):
        failed = TestResult(status="failed", summary="install ok · build failed (exit 1)",
                                        failures=[{"name": "npm run build", "message": "boom"}])
        with mock.patch.object(test_runner, "run_project_checks", return_value=failed):
            code, out = run_script(["--target", "generated/tpl", "--check"], self.root)
        self.assertEqual(code, 1, out)
        self.assertIn("status: failed", out)
        self.assertIn("failure: npm run build: boom", out)


@unittest.skipUnless(os.environ.get("RUN_NPM_TESTS") == "1", "set RUN_NPM_TESTS=1 (needs network for npm install)")
class RealTemplateTest(TempRoot):
    def test_template_builds_and_passes_its_tests(self):
        """Done-when (M19): a project created from the template installs, builds and passes 3/3 tests."""
        code, out = run_script(["--target", "generated/tpl-real", "--check"], self.root)
        self.assertEqual(code, 0, out)
        self.assertRegex(out, re.escape("status: passed (") + r".*tests 3/3 passed")
        self.assertTrue((self.root / "generated/tpl-real/dist/index.html").is_file())


if __name__ == "__main__":
    unittest.main()
