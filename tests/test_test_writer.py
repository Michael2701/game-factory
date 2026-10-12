import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))  # shared helpers (fakes.py) when run as a single module

from agents.nodes.test_writer import check_tests, write_tests  # noqa: E402
from agents.prompts import load_prompt  # noqa: E402
from agents.schemas import FileChangeSet, NodeError  # noqa: E402
from agents.schemas.examples import sample_game_spec  # noqa: E402
from agents.tools.filesystem import file_hashes  # noqa: E402
from fakes import FakeLLM  # noqa: E402

SPEC = sample_game_spec()  # test_requirements mention window.__TEST_API__

GOOD_TS = """import { test, expect } from '@playwright/test';

test('loads', async ({ page }) => {
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__GAME_STATE__?.scene === 'StartScene');
});

test('collision loses', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => (window as any).__TEST_API__.spawnBlockAbovePlayer());
  await page.waitForFunction(() => (window as any).__GAME_STATE__.isGameOver === true);
});

test('surviving wins', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => (window as any).__TEST_API__.skipTime(60));
  expect(await page.evaluate(() => (window as any).__GAME_STATE__.result)).toBe('win');
});
"""


def change(path="tests/game.spec.ts", content=GOOD_TS, operation="create"):
    return {"path": path, "operation": operation, "content": content, "reason": "tests"}


def reply(*changes) -> str:
    return json.dumps({"changes": list(changes)})


VALID = reply(change())


def errors_for(raw: str, project_files=None, spec=SPEC) -> list[str]:
    return check_tests(FileChangeSet.model_validate_json(raw), spec, project_files or {})


class CheckTestsTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(errors_for(VALID), [])
        config = change("playwright.config.ts", "import { defineConfig } from '@playwright/test';\nexport default defineConfig({});\n")
        self.assertEqual(errors_for(reply(change(), config)), [])

    def test_update_existing(self):
        self.assertEqual(errors_for(reply(change(operation="update")), {"tests/game.spec.ts": "old"}), [])

    def test_file_rules(self):
        cases = {
            "must contain 'tests/game.spec.ts'": reply(),
            "only 'tests/game.spec.ts'": reply(change(), change("src/main.ts")),
            "duplicate change": reply(change(), change()),
            "content must not be empty": reply(change(content="  \n")),
            "without markdown code fences": reply(change(content="```ts\n" + GOOD_TS + "```")),
            "delete is not allowed": reply({"path": "tests/game.spec.ts", "operation": "delete", "reason": "r"}),
            "use operation 'create'": reply(change(operation="update")),
        }
        for needle, raw in cases.items():
            with self.subTest(needle=needle):
                errors = errors_for(raw)
                self.assertTrue(any(needle in e for e in errors), errors)

    def test_existing_config_and_test_file(self):
        project = {"tests/game.spec.ts": "old", "playwright.config.ts": "x"}
        errors = errors_for(reply(change(), change("playwright.config.ts", "x", "update")), project)
        self.assertTrue(any("use operation 'update'" in e for e in errors), errors)
        self.assertTrue(any("already exists; do not change it" in e for e in errors), errors)

    def test_code_rules(self):
        cases = {
            "must import { test, expect } from '@playwright/test'": GOOD_TS.replace("@playwright/test", "playwright"),
            "import from 'fs' is not allowed": "import fs from 'fs';\n" + GOOD_TS,
            "import from 'node:child_process' is not allowed": "import { exec } from 'node:child_process';\n" + GOOD_TS,
            "'require(' is not allowed": GOOD_TS + "\nconst x = require('os');\n",
            "'waitForTimeout' is not allowed": GOOD_TS + "\n// await page.waitForTimeout(1000);\n",
            "'setTimeout' is not allowed": GOOD_TS + "\nsetTimeout(() => {}, 1);\n",
            "'Math.random' is not allowed": GOOD_TS + "\nconst r = Math.random();\n",
            "needs at least 3 test(...) cases": GOOD_TS.split("test('collision")[0],
            "page.goto('http://evil.example') is not allowed": GOOD_TS.replace("page.goto('/')", "page.goto('http://evil.example')", 1),
            "must load the game with page.goto('/')": GOOD_TS.replace("page.goto('/')", "page.reload()"),
            "must read game state through window.__GAME_STATE__": GOOD_TS.replace("__GAME_STATE__", "state"),
            "the tests must use it too": GOOD_TS.replace("__TEST_API__", "api"),
        }
        for needle, code in cases.items():
            with self.subTest(needle=needle):
                errors = errors_for(reply(change(content=code)))
                self.assertTrue(any(needle in e for e in errors), errors)

    def test_test_api_optional_when_spec_does_not_use_it(self):
        spec = SPEC.model_copy(update={"test_requirements": ["the game shows a title"]})
        self.assertEqual(errors_for(reply(change(content=GOOD_TS.replace("__TEST_API__", "api"))), spec=spec), [])

    def test_hooks_must_exist_in_project(self):
        hooks = {"src/testHooks.ts": "window.__TEST_API__ = { spawnBlockAbovePlayer() {}, skipTime() {} };\n"
                                     "window.__GAME_STATE__ = { scene: '', isGameOver: false, result: null };"}
        self.assertEqual(errors_for(VALID, hooks), [])
        code = GOOD_TS.replace("spawnBlockAbovePlayer()", "collideWithWall()")
        errors = errors_for(reply(change(content=code)), hooks)
        self.assertTrue(any("['__TEST_API__.collideWithWall'] are not defined" in e for e in errors), errors)
        hook_error = next(e for e in errors if "are not defined" in e)
        self.assertIn("Available hooks:\n--- src/testHooks.ts ---\n", hook_error)  # repair sees the real hooks
        self.assertIn("spawnBlockAbovePlayer() {}", hook_error)

    def test_any_hooks_allowed_without_hook_files(self):
        code = GOOD_TS.replace("spawnBlockAbovePlayer()", "collideWithWall()")
        self.assertEqual(errors_for(reply(change(content=code)), {"src/main.ts": "const a = 1;"}), [])

    def test_scene_must_be_awaited(self):
        """M20 real run: tests read the scene right after an action; the switch happens on the next frame."""
        racy = GOOD_TS + ("test('ends', async ({ page }) => { await page.goto('/');\n"
                          "  expect(await page.evaluate(() => (window as any).__GAME_STATE__.scene)).toBe('GameOverScene'); });\n")
        errors = errors_for(reply(change(content=racy)))
        self.assertTrue(any("scene changes take effect on the next frame" in e for e in errors), errors)
        awaited = GOOD_TS + ("test('ends', async ({ page }) => { await page.goto('/');\n"
                             "  await page.waitForFunction(() => (window as any).__GAME_STATE__.scene === 'GameOverScene'); });\n")
        self.assertFalse([e for e in errors_for(reply(change(content=awaited))) if "next frame" in e])

    def test_prompt_example_passes(self):
        example = load_prompt("test_writer").split("## Example output", 1)[1]
        raw = example.split("```json\n", 1)[1].split("\n```", 1)[0]
        self.assertEqual(errors_for(raw), [])


class WriteTestsTest(unittest.TestCase):
    def test_valid_first_try(self):
        llm = FakeLLM(f"```json\n{VALID}\n```")
        result = write_tests(SPEC, llm=llm)
        self.assertIsInstance(result, FileChangeSet)
        self.assertEqual([c.path for c in result.changes], ["tests/game.spec.ts"])
        self.assertEqual(len(llm.prompts), 1)
        self.assertIn('"slug": "block-dodger"', llm.prompts[0])
        self.assertIn("Project files (paths, and content where relevant):\n\n(none)", llm.prompts[0])

    def test_project_files_shown_readably(self):
        llm = FakeLLM(VALID)
        write_tests(SPEC, {"src/main.ts": "const a = 1;\n"}, llm=llm)
        self.assertIn("=== src/main.ts ===\nconst a = 1;\n=== end of src/main.ts ===", llm.prompts[0])

    def test_violation_repaired(self):
        bad = reply(change(content=GOOD_TS + "\nawait page.waitForTimeout(500);\n"))
        llm = FakeLLM(bad, VALID)
        self.assertIsInstance(write_tests(SPEC, llm=llm), FileChangeSet)
        self.assertEqual(len(llm.prompts), 2)
        self.assertIn("'waitForTimeout' is not allowed", llm.prompts[1])

    def test_repair_fails(self):
        result = write_tests(SPEC, llm=FakeLLM(reply(), reply()))
        self.assertIsInstance(result, NodeError)
        self.assertEqual((result.node, result.attempts), ("test_writer", 2))

    def test_llm_exception(self):
        result = write_tests(SPEC, llm=FakeLLM(ConnectionError("down")))
        self.assertIsInstance(result, NodeError)
        self.assertIn("ConnectionError: down", result.message)

    def test_no_files_written(self):
        before = file_hashes()
        write_tests(SPEC, llm=FakeLLM(VALID))
        write_tests(SPEC, llm=FakeLLM("nonsense", "nonsense"))
        self.assertEqual(file_hashes(), before)


class FileHashesTest(unittest.TestCase):
    def test_detects_changes_and_skips_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("1")
            (root / "node_modules/pkg").mkdir(parents=True)
            (root / "node_modules/pkg/x.js").write_text("x")
            first = file_hashes(root)
            self.assertEqual(list(first), ["a.txt"])
            (root / "a.txt").write_text("2")
            self.assertNotEqual(file_hashes(root), first)


class RunnerTest(unittest.TestCase):
    def run_script(self, *args, timeout=60):
        return subprocess.run([sys.executable, "scripts/run_test_writer_dry_run.py", *args], cwd=ROOT,
                              capture_output=True, text=True, timeout=timeout)

    def test_bad_spec(self):
        self.assertEqual(self.run_script("--spec", "README.md").returncode, 2)

    def test_bad_project_dir(self):
        for project_dir in ["/etc", "generated/does-not-exist"]:
            with self.subTest(project_dir=project_dir):
                proc = self.run_script("--project-dir", project_dir)
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertIn("bad input", proc.stderr)

    @unittest.skipUnless(os.environ.get("RUN_OLLAMA_TESTS") == "1", "set RUN_OLLAMA_TESTS=1 (needs `ollama serve`)")
    def test_done_when_command(self):
        before = file_hashes()
        proc = self.run_script("--json", timeout=600)
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
        changes = FileChangeSet.model_validate_json(proc.stdout)
        self.assertEqual(check_tests(changes, SPEC, {}), [])
        self.assertIn("tests/game.spec.ts", [c.path for c in changes.changes])
        self.assertEqual(file_hashes(), before)


if __name__ == "__main__":
    unittest.main()
