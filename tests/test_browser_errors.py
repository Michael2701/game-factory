"""M21 browser-error visibility: fixtures import, debug build env, source-map frame mapping.

Gated (RUN_NPM_TESTS=1): a template project with a deliberate exception in GameScene fails
with "Browser errors" pointing at src/scenes/GameScene.ts; the clean template still passes.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.generators.phaser_template import LOCKED_FILES, instantiate  # noqa: E402
from agents.nodes import test_runner  # noqa: E402
from agents.nodes.test_writer import check_tests, normalize_tests, test_module  # noqa: E402
from agents.schemas import CommandResult, FileChange, FileChangeSet  # noqa: E402
from agents.schemas.examples import sample_game_spec  # noqa: E402
from agents.tools.apply_changes import apply_changes  # noqa: E402
from agents.generators.phaser_template import template_changes  # noqa: E402
from agents.tools.sourcemap import SourceMap, decode_vlq, map_frames  # noqa: E402

TEMPLATE = instantiate("x", "X")


class SourceMapTest(unittest.TestCase):
    def test_vlq(self):
        self.assertEqual(decode_vlq("AAAA"), [0, 0, 0, 0])
        self.assertEqual(decode_vlq("AACA"), [0, 0, 1, 0])
        self.assertEqual(decode_vlq("D"), [-1])
        self.assertEqual(decode_vlq("gB"), [16])

    def test_lookup_and_frame_rewrite(self):
        # line 1: col 0 -> src 0 line 0 col 0; col 10 -> src 0 line 4 col 2 ; line 2: col 0 -> src 1 line 0
        data = {"version": 3, "sources": ["../../node_modules/phaser/x.js", "../../src/scenes/GameScene.ts"],
                "mappings": "AAAA,UAIE;ACJF"}
        sm = SourceMap(data)
        self.assertEqual(sm.lookup(1, 1), ("../../node_modules/phaser/x.js", 1, 1))
        self.assertEqual(sm.lookup(1, 15), ("../../node_modules/phaser/x.js", 5, 3))
        self.assertEqual(sm.lookup(2, 1), ("../../src/scenes/GameScene.ts", 1, 1))
        self.assertIsNone(sm.lookup(9, 1))
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "dist/assets").mkdir(parents=True)
            (project / "dist/assets/index-ab.js.map").write_text(json.dumps(data))
            text = "TypeError: x\n    at GameScene.create (http://127.0.0.1:41731/assets/index-ab.js:2:5)"
            self.assertIn("at GameScene.create (src/scenes/GameScene.ts:1:1 (index-ab.js:2:5))",
                          map_frames(text, project))
            missing = "at f (http://127.0.0.1:41731/assets/other.js:1:1)"
            self.assertEqual(map_frames(missing, project), missing)  # no map: raw frame stays
            (project / "dist/assets/bad.js.map").write_text("{not json")
            bad = "at f (http://127.0.0.1:41731/assets/bad.js:1:1)"
            self.assertEqual(map_frames(bad, project), bad)


class FixturesImportTest(unittest.TestCase):
    TESTS = ("import { test, expect } from '@playwright/test';\n" + "".join(
        f"test('t{i}', async ({{ page }}) => {{\n  await page.goto('/');\n"
        f"  await page.waitForFunction(() => (window as any).__GAME_STATE__?.scene === 'StartScene');\n}});\n"
        for i in range(3)))

    def test_module_depends_on_template(self):
        self.assertEqual(test_module(TEMPLATE), "./fixtures")
        self.assertEqual(test_module({}), "@playwright/test")

    def test_normalizer_rewrites_import_and_check_requires_fixtures(self):
        changes = FileChangeSet(changes=[FileChange(path="tests/game.spec.ts", operation="update",
                                                    content=self.TESTS, reason="tests")])
        errors = check_tests(changes, sample_game_spec(), TEMPLATE)
        self.assertIn("tests/game.spec.ts: must import { test, expect } from './fixtures'", errors)
        normalized = normalize_tests(changes, "./fixtures")
        self.assertTrue(normalized.changes[0].content.startswith("import { test, expect } from './fixtures';"))
        self.assertIn("imports test/expect from './fixtures'", normalized.changes[0].reason)
        self.assertFalse([e for e in check_tests(normalized, sample_game_spec(), TEMPLATE) if "import" in e])

    def test_new_files_are_locked(self):
        for path in ("vite.config.ts", "tests/fixtures.ts", "tests/acceptance.spec.ts"):
            self.assertIn(path, LOCKED_FILES)

    def test_template_files(self):
        self.assertIn("page.on('pageerror'", TEMPLATE["tests/fixtures.ts"])
        self.assertIn("message.type() === 'error'", TEMPLATE["tests/fixtures.ts"])
        self.assertIn("process.env.GAME_FACTORY_DEBUG_BUILD === '1'", TEMPLATE["vite.config.ts"])
        self.assertIn('<link rel="icon" href="data:," />', TEMPLATE["index.html"])


class DebugBuildEnvTest(unittest.TestCase):
    def test_only_the_build_step_gets_the_debug_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "generated/g/tests").mkdir(parents=True)
            (root / "generated/g/package.json").write_text("{}")
            (root / "generated/g/tests/game.spec.ts").write_text("//")
            ok = CommandResult(command="c", cwd="generated/g", exit_code=0, stdout="{}", duration_s=0.1)
            with mock.patch.object(test_runner, "run_command", return_value=ok) as run:
                test_runner.run_project_checks("generated/g", root=root)
        envs = [c.kwargs["extra_env"] for c in run.call_args_list]
        self.assertEqual(envs, [None, {"GAME_FACTORY_DEBUG_BUILD": "1"}, None])


@unittest.skipUnless(os.environ.get("RUN_NPM_TESTS") == "1", "set RUN_NPM_TESTS=1 (needs network for npm install)")
class RealBrowserErrorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "generated").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_exception_in_game_scene_is_reported_with_source_file(self):
        target = "generated/boom"
        result = apply_changes(template_changes("boom", "Boom"), target, apply=True, root=self.root)
        self.assertTrue(result.ok, result.summary())
        scene = self.root / target / "src/scenes/GameScene.ts"
        scene.write_text(scene.read_text().replace("    this.result = null;\n",
                                                   "    this.result = null;\n    this.time.delayedCall(0, () => { throw new Error('boom in game loop'); });\n", 1))
        checks = test_runner.run_project_checks(target, root=self.root)
        self.assertEqual(checks.status, "failed", checks.summary)
        text = "\n".join(f.message for f in checks.failures)
        self.assertIn("Browser errors:", text)
        self.assertIn("boom in game loop", text)  # uncaught in the game loop: only the fixture sees it
        self.assertIn("src/scenes/GameScene.ts:", text)  # mapped from the bundle via the source map
        self.assertFalse((self.root / target / "dist/assets").exists() and not any(
            p.suffix == ".map" for p in (self.root / target / "dist/assets").iterdir()))


if __name__ == "__main__":
    unittest.main()
