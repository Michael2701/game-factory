import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.generators.minimal_project import generate_minimal_project  # noqa: E402
from agents.nodes import test_runner as tr  # noqa: E402
from agents.schemas import CommandResult, FactoryStatus, GameFactoryState  # noqa: E402
from agents.schemas.examples import sample_game_spec  # noqa: E402
from agents.tools.commands import MAX_OUTPUT_CHARS  # noqa: E402
from agents.tools.safety import SafetyError  # noqa: E402

PROJECT = "generated/game"
PLAYWRIGHT_VERSION = "1.62.0"  # matches the cached chromium-1234 (no browser download)

REPORT = {
    "suites": [{
        "title": "game.spec.ts", "file": "game.spec.ts", "specs": [
            {"title": "loads", "ok": True, "tests": [{"results": [{"status": "passed"}]}]},
        ],
        "suites": [{"title": "gameplay", "specs": [
            {"title": "wins", "ok": False, "tests": [{"results": [
                {"status": "failed", "errors": [{"message": "\u001b[31mError: expected 'win'\u001b[39m\nreceived 'lose'"}]}]}]},
        ]}],
    }],
    "errors": [],
}


def cmd(command, exit_code=0, stdout="", timed_out=False):
    return CommandResult(command=command, cwd=PROJECT, exit_code=exit_code, stdout=stdout,
                         stderr="boom" if exit_code else "", duration_s=0.1, timed_out=timed_out)


class Sandbox(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / PROJECT / "tests").mkdir(parents=True)
        (self.root / PROJECT / "package.json").write_text("{}")

    def tearDown(self):
        self._tmp.cleanup()

    def add_test_file(self):
        (self.root / PROJECT / "tests/game.spec.ts").write_text("// tests")

    def run_checks(self, side_effect, steps=tr.STEPS):
        with mock.patch.object(tr, "run_command", side_effect=side_effect) as run:
            result = tr.run_project_checks(PROJECT, steps, root=self.root)
        return result, [c.args[0] for c in run.call_args_list]


class RunChecksTest(Sandbox):
    def test_all_ok_without_tests(self):
        result, calls = self.run_checks([cmd("npm install"), cmd("npm run build")])
        self.assertEqual(result.status, "passed")
        self.assertEqual(calls, ["npm install", "npm run build"])
        self.assertEqual(result.summary, "install ok · build ok · no tests found (tests/*.spec.ts)")
        self.assertEqual(len(result.command_results), 2)

    def test_all_ok_with_tests(self):
        self.add_test_file()
        passing = json.dumps({"suites": [{"title": "a", "specs": [{"title": "t", "ok": True}]}]})
        result, calls = self.run_checks([cmd("npm install"), cmd("npm run build"), cmd("npx playwright test", 0, passing)])
        self.assertEqual(result.status, "passed")
        self.assertEqual(calls[-1], "npx playwright test --reporter=json")
        self.assertIn("tests 1/1 passed", result.summary)

    def test_build_failure_stops(self):
        self.add_test_file()
        result, calls = self.run_checks([cmd("npm install"), cmd("npm run build", 1, "src/main.ts:3 error")])
        self.assertEqual(result.status, "failed")
        self.assertEqual(calls, ["npm install", "npm run build"])
        self.assertEqual(result.failures[0].name, "npm run build")
        self.assertIn("boom", result.failures[0].message)
        self.assertIn("src/main.ts:3 error", result.failures[0].message)

    def test_failure_message_drops_node_modules_frames(self):
        noisy = CommandResult(command="npm run build", cwd=PROJECT, exit_code=1, duration_s=0.1, stdout="> vite build",
                              stderr="[vite] Unexpected token\n ─[ src/main.ts:1:11 ]\n"
                                     "    at build (file:///x/node_modules/vite/dist/node.js:1:1)\n"
                                     "    at async run (file:///x/node_modules/rolldown/a.mjs:2:2) {\n"
                                     "  errors: [Getter/Setter]\n}")
        result, _ = self.run_checks([cmd("npm install"), noisy])
        message = result.failures[0].message
        self.assertIn("src/main.ts:1:11", message)
        self.assertIn("> vite build", message)
        self.assertNotIn("node_modules", message)
        self.assertNotIn("Getter/Setter", message)

    def test_install_failure_is_fixable(self):
        result, _ = self.run_checks([cmd("npm install", 1)])
        self.assertEqual((result.status, result.failures[0].name), ("failed", "npm install"))

    def test_failing_tests_parsed(self):
        self.add_test_file()
        result, _ = self.run_checks([cmd("npm install"), cmd("npm run build"), cmd("npx playwright test", 1, json.dumps(REPORT))])
        self.assertEqual(result.status, "failed")
        self.assertEqual([f.name for f in result.failures], ["game.spec.ts › gameplay › wins"])
        self.assertEqual(result.failures[0].message, "Error: expected 'win'\nreceived 'lose'")  # ANSI stripped
        self.assertIn("tests 1/2 passed", result.summary)

    def test_large_report_parsed_and_stored_short(self):
        """M19 regression: a 9-test report with failures (46 KB) was cut to the 20k tail and not parsed."""
        self.add_test_file()
        report = {"suites": [{"title": "game.spec.ts", "specs": [
            {"title": f"t{i}", "ok": False, "tests": [{"results": [{"status": "failed",
                                                                    "errors": [{"message": f"E{i} " + "x" * 6000}]}]}]}
            for i in range(9)]}], "errors": []}
        stdout = json.dumps(report)
        self.assertGreater(len(stdout), MAX_OUTPUT_CHARS)
        result, _ = self.run_checks([cmd("npm install"), cmd("npm run build"), cmd("npx playwright test", 1, stdout)])
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.summary, "install ok · build ok · tests 0/9 passed")
        self.assertEqual([f.name for f in result.failures], [f"game.spec.ts › t{i}" for i in range(9)])
        self.assertLessEqual(len(result.command_results[-1].stdout), MAX_OUTPUT_CHARS + 20)  # state stays small

    def test_report_limit_passed_to_command_runner(self):
        self.add_test_file()
        with mock.patch.object(tr, "run_command", side_effect=[cmd("npm install"), cmd("npm run build"),
                                                               cmd("npx playwright test", 0, "{}")]) as run:
            tr.run_project_checks(PROJECT, root=self.root)
        limits = [c.kwargs["max_output_chars"] for c in run.call_args_list]
        self.assertEqual(limits, [MAX_OUTPUT_CHARS, MAX_OUTPUT_CHARS, tr.REPORT_MAX_CHARS])

    def test_unparsable_report(self):
        self.add_test_file()
        result, _ = self.run_checks([cmd("npm install"), cmd("npm run build"), cmd("npx playwright test", 1, "garbage")])
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failures[0].name, "npx playwright test --reporter=json")
        self.assertIn("report not parsed", result.summary)

    def test_timeout_is_error(self):
        result, _ = self.run_checks([cmd("npm install", -1, timed_out=True)])
        self.assertEqual(result.status, "error")
        self.assertIn("install timed out", result.summary)

    def test_safety_error_is_error(self):
        result, _ = self.run_checks(SafetyError("npm run build: scripts.prebuild is not allowed"), steps=("build",))
        self.assertEqual(result.status, "error")
        self.assertIn("prebuild", result.summary)

    def test_steps_subset_and_unknown(self):
        _, calls = self.run_checks([cmd("npm run build")], steps=("build",))
        self.assertEqual(calls, ["npm run build"])
        result, calls = self.run_checks([], steps=("deploy",))
        self.assertEqual((result.status, calls), ("error", []))

    def test_missing_or_bad_project(self):
        for project in ["generated/missing", "/etc", ".git"]:
            with self.subTest(project=project):
                result = tr.run_project_checks(project, root=self.root)
                self.assertEqual(result.status, "error")


class ParseReportTest(unittest.TestCase):
    def test_parse(self):
        total, failures = tr.parse_playwright_json("Running 2 tests\n" + json.dumps(REPORT))
        self.assertEqual(total, 2)
        self.assertEqual(len(failures), 1)

    def test_top_level_errors(self):
        total, failures = tr.parse_playwright_json(json.dumps({"suites": [], "errors": [{"message": "No tests found"}]}))
        self.assertEqual((total, failures[0].name, failures[0].message), (0, "playwright", "No tests found"))

    def test_unparsable(self):
        self.assertIsNone(tr.parse_playwright_json("no json"))
        self.assertIsNone(tr.parse_playwright_json('{"truncated": '))


class NodeTest(Sandbox):
    def test_state_updates(self):
        spec = sample_game_spec()
        state = GameFactoryState(user_idea="idea", game_spec=spec, command_results=[cmd("earlier")])
        cases = {
            "passed": (FactoryStatus.TESTS_PASSED, None),
            "failed": (FactoryStatus.TESTS_FAILED, None),
            "error": (FactoryStatus.ERROR, "test_runner: x"),
        }
        for status, (expected, error) in cases.items():
            with self.subTest(status=status):
                fake = tr.TestResult(status=status, command_results=[cmd("npm run build")], summary="x")
                with mock.patch.object(tr, "run_project_checks", return_value=fake) as run:
                    update = tr.test_runner_node(state)
                run.assert_called_once_with("generated/block-dodger", root=tr.PROJECT_ROOT)
                self.assertEqual(update["status"], expected)
                self.assertEqual(update["error"], error)
                self.assertEqual([c.command for c in update["command_results"]], ["earlier", "npm run build"])

    def test_no_spec_no_dir(self):
        update = tr.test_runner_node(GameFactoryState(user_idea="idea"))
        self.assertEqual(update["status"], FactoryStatus.ERROR)


class ScriptTest(unittest.TestCase):
    def test_missing_project_exit_2(self):
        proc = subprocess.run([sys.executable, "scripts/run_test_runner.py", "--project-dir", "generated/missing"],
                              cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("status: error", proc.stdout)


@unittest.skipUnless(os.environ.get("RUN_NPM_TESTS") == "1", "set RUN_NPM_TESTS=1 (needs network for npm install)")
class RealProjectTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "generated").mkdir()
        report = generate_minimal_project("generated/real", title="Real Game", build=False, root=self.root)
        self.assertTrue(report.ok, report.error)
        self.project = self.root / "generated/real"

    def tearDown(self):
        self._tmp.cleanup()

    def test_minimal_project_passes(self):
        result = tr.run_project_checks("generated/real", root=self.root)
        self.assertEqual(result.status, "passed", result.summary)

    def test_broken_build_fails_with_vite_error(self):
        (self.project / "src/main.ts").write_text("const x = ;\n")
        result = tr.run_project_checks("generated/real", root=self.root)
        self.assertEqual(result.status, "failed", result.summary)
        self.assertEqual(result.failures[0].name, "npm run build")
        self.assertIn("main.ts", result.failures[0].message)

    def test_real_playwright_run(self):
        """@playwright/test 1.62.0 uses the cached chromium-1234: no browser download."""
        port = random.randint(41000, 41999)
        package = json.loads((self.project / "package.json").read_text())
        package["devDependencies"]["@playwright/test"] = PLAYWRIGHT_VERSION
        (self.project / "package.json").write_text(json.dumps(package, indent=2))
        (self.project / "playwright.config.ts").write_text(f"""import {{ defineConfig }} from '@playwright/test';

export default defineConfig({{
  testDir: 'tests',
  use: {{ baseURL: 'http://127.0.0.1:{port}', browserName: 'chromium', headless: true }},
  webServer: {{ command: 'npx vite preview --port {port} --strictPort --host 127.0.0.1', url: 'http://127.0.0.1:{port}', timeout: 60000 }},
}});
""")
        (self.project / "tests").mkdir()
        (self.project / "tests/game.spec.ts").write_text("""import { test, expect } from '@playwright/test';

test('game state is ready', async ({ page }) => {
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__GAME_STATE__?.ready === true);
  expect(await page.evaluate(() => (window as any).__GAME_STATE__.title)).toBe('Real Game');
});

test('deliberately failing', async ({ page }) => {
  await page.goto('/');
  expect(await page.evaluate(() => (window as any).__GAME_STATE__.title)).toBe('Another Game');
});
""")
        result = tr.run_project_checks("generated/real", root=self.root)
        self.assertEqual(result.status, "failed", result.summary + "\n" + "\n".join(f.message for f in result.failures))
        self.assertEqual([f.name for f in result.failures], ["game.spec.ts › deliberately failing"])
        self.assertIn("Another Game", result.failures[0].message)
        self.assertIn("tests 1/2 passed", result.summary)


if __name__ == "__main__":
    unittest.main()
