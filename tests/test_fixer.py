import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agents.fixtures.broken_projects import BASE_FILES, CASES, import_case, phaser_default_case  # noqa: E402
from agents.nodes.fixer import (  # noqa: E402
    MAX_FILES,
    check_fix,
    changed_lines,
    fix,
    fixer_node,
    mentioned_paths,
    relevant_files,
)
from agents.schemas import (  # noqa: E402
    FactoryStatus,
    FileChange,
    FileChangeSet,
    GameFactoryState,
    NodeError,
    TestFailure,
    TestResult,
)
from agents.schemas.examples import BLOCK_DODGER_IDEA, sample_game_spec, sample_task_plan  # noqa: E402
from agents.tools.filesystem import file_hashes  # noqa: E402
from fakes import FakeLLM  # noqa: E402
from scripts import run_fixer_dry_run  # noqa: E402

PHASER = phaser_default_case()
IMPORT = import_case()
FIXED_START = BASE_FILES["src/scenes/StartScene.ts"]
BROKEN_START = PHASER.files["src/scenes/StartScene.ts"]


def fc(path, op, content=None, patch=None):
    return FileChange(path=path, operation=op, content=content, patch=patch, reason="r")


def reply(*changes) -> str:
    return json.dumps({"changes": [{"path": p, "operation": op, "content": c, "reason": "fix"} for p, op, c in changes]})


GOOD_REPLY = reply(("src/scenes/StartScene.ts", "update", FIXED_START))


def test_failure(name: str, message: str) -> TestResult:
    return TestResult(status="failed", failures=[TestFailure(name=name, message=message)], summary="failed")


class FixturesTest(unittest.TestCase):
    def test_each_case_has_one_bug_in_its_culprit(self):
        for name, make in CASES.items():
            case = make()
            with self.subTest(case=name):
                self.assertEqual(sorted(p for p in case.files if case.files[p] != BASE_FILES[p]),
                                 sorted([case.culprit, *case.also_broken]))
                self.assertFalse(case.is_fixed(case.files[case.culprit]))
                self.assertTrue(case.is_fixed(BASE_FILES[case.culprit]))
                self.assertEqual(case.test_result.status, "failed")


class RelevantFilesTest(unittest.TestCase):
    def test_mentioned_paths(self):
        self.assertEqual(mentioned_paths(PHASER.test_result), ["src/scenes/StartScene.ts"])
        self.assertEqual(mentioned_paths(IMPORT.test_result), ["src/main.ts"])
        result = test_failure("tests/game.spec.ts › win", "at /abs/generated/x/src/testHooks.ts:4:2\n../src/evil.ts")
        self.assertEqual(mentioned_paths(result), ["tests/game.spec.ts", "src/testHooks.ts", "src/evil.ts"])

    def test_named_source_file_plus_entry_and_package(self):
        relevant, creatable = relevant_files(PHASER.test_result, PHASER.files)
        self.assertEqual(list(relevant), ["src/scenes/StartScene.ts", "package.json", "src/main.ts"])
        self.assertEqual(creatable, [])

    def test_no_source_file_named_means_whole_project(self):
        result = test_failure("tests/game.spec.ts › surviving 60 seconds wins", "Timeout 30000ms exceeded")
        relevant, _ = relevant_files(result, BASE_FILES)
        self.assertEqual(relevant, {p: c for p, c in BASE_FILES.items() if p != "playwright.config.ts"})

    def test_playwright_config_only_when_named(self):
        result = test_failure("playwright", "Error: playwright.config.ts: webServer exited early")
        relevant, _ = relevant_files(result, BASE_FILES)
        self.assertIn("playwright.config.ts", relevant)

    def test_missing_named_file_is_creatable(self):
        files = {p: c for p, c in BASE_FILES.items() if p != "playwright.config.ts"}
        result = test_failure("npx playwright test", "Error: Cannot find module playwright.config.ts")
        relevant, creatable = relevant_files(result, files)
        self.assertEqual(creatable, ["playwright.config.ts"])
        self.assertEqual(relevant, files)


class CheckFixTest(unittest.TestCase):
    def setUp(self):
        self.relevant, self.creatable = relevant_files(PHASER.test_result, PHASER.files)

    def errors(self, *changes, creatable=None):
        return check_fix(FileChangeSet(changes=list(changes)), self.relevant,
                         self.creatable if creatable is None else creatable)

    def test_minimal_fix_ok(self):
        self.assertEqual(self.errors(fc("src/scenes/StartScene.ts", "update", FIXED_START)), [])
        self.assertEqual(changed_lines(BROKEN_START, FIXED_START), 2)

    def test_no_changes_is_valid(self):
        self.assertEqual(self.errors(), [])

    def test_rejections(self):
        start = "src/scenes/StartScene.ts"
        cases = {
            "not allowed": (fc("src/scenes/GameScene.ts", "update", "x\n"), "path is not allowed"),
            "delete": (fc(start, "delete"), "delete is not allowed"),
            "create existing": (fc(start, "create", FIXED_START), "already exists"),
            "identical": (fc(start, "update", BROKEN_START), "identical"),
            "fences": (fc(start, "update", "```ts\n" + FIXED_START + "```\n"), "code fences"),
            "patch": (fc(start, "update", patch="@@ -1 +1 @@"), "patch is not supported"),
            "rewrite": (fc(start, "update", "\n".join(f"// line {i}" for i in range(40)) + "\n"), "changed lines"),
            "package.json": (fc("package.json", "update", json.dumps({"scripts": {"build": "rm -rf /"}})),
                             "scripts.build"),
        }
        for name, (change, needle) in cases.items():
            with self.subTest(case=name):
                errors = self.errors(change)
                self.assertTrue(any(needle in e for e in errors), errors)

    def test_create_only_named_missing_files(self):
        config = fc("playwright.config.ts", "create", "export default {};\n")
        self.assertTrue(any("not allowed" in e for e in self.errors(config)))
        self.assertEqual(self.errors(config, creatable=["playwright.config.ts"]), [])
        update_missing = fc("playwright.config.ts", "update", "export default {};\n")
        self.assertTrue(any("does not exist yet" in e for e in self.errors(update_missing,
                                                                          creatable=["playwright.config.ts"])))

    def test_too_many_files_and_duplicates(self):
        relevant = dict(BASE_FILES)
        changes = [fc(p, "update", c + "// x\n") for p, c in list(relevant.items())[:MAX_FILES + 1]]
        errors = check_fix(FileChangeSet(changes=changes), relevant, [])
        self.assertTrue(any(f"at most {MAX_FILES} files" in e for e in errors), errors)
        dup = [fc("src/main.ts", "update", BASE_FILES["src/main.ts"] + "// a\n")] * 2
        self.assertTrue(any("duplicate" in e for e in check_fix(FileChangeSet(changes=dup), relevant, [])))

    def test_tests_must_not_be_weakened(self):
        relevant = dict(BASE_FILES)
        tests = BASE_FILES["tests/game.spec.ts"]
        skipped = tests.replace("test('surviving 60 seconds wins'", "test.skip('surviving 60 seconds wins'")
        fewer = tests[:tests.index("test('the game scene starts'")]
        for content, needle in [(skipped, "test.skip/only/fixme"), (fewer, "removes tests")]:
            with self.subTest(needle=needle):
                errors = check_fix(FileChangeSet(changes=[fc("tests/game.spec.ts", "update", content)]), relevant, [])
                self.assertTrue(any(needle in e for e in errors), errors)


    def test_timeouts_must_not_be_raised(self):
        """Seen in M16 with real qwen: a win-logic timeout 'fixed' by raising the config timeout."""
        relevant = dict(BASE_FILES)
        tests = BASE_FILES["tests/game.spec.ts"]
        config = BASE_FILES["playwright.config.ts"]
        cases = {
            "config timeout": ("playwright.config.ts", config.replace("timeout: 15000", "timeout: 30000")),
            "spec wait": ("tests/game.spec.ts", tests.replace("  await page.waitForFunction(() => (window as any).__GAME_STATE__.result === 'win');",
                                                              "  await page.waitForTimeout(5000);\n  await page.waitForFunction(() => (window as any).__GAME_STATE__.result === 'win');")),
            "spec option": ("tests/game.spec.ts", tests.replace(".result === 'win');", ".result === 'win', null, { timeout: 60000 });")),
        }
        for name, (path, content) in cases.items():
            with self.subTest(name):
                self.assertNotEqual(content, relevant[path])
                errors = check_fix(FileChangeSet(changes=[fc(path, "update", content)]), relevant, [])
                self.assertTrue(any("raises a timeout" in e for e in errors), errors)
        game_scene = BASE_FILES["src/scenes/GameScene.ts"].replace("timeLeft = 60;", "timeLeft = 60; // timeout\n", 1)
        errors = check_fix(FileChangeSet(changes=[fc("src/scenes/GameScene.ts", "update", game_scene)]), relevant, [])
        self.assertFalse(any("raises a timeout" in e for e in errors), errors)  # game code may mention timeouts


class FixTest(unittest.TestCase):
    def run_fix(self, llm, case=PHASER):
        return fix(case.test_result, case.files, sample_game_spec(), sample_task_plan(), llm=llm)

    def test_valid_fix(self):
        llm = FakeLLM(GOOD_REPLY)
        result = self.run_fix(llm)
        self.assertIsInstance(result, FileChangeSet)
        self.assertTrue(PHASER.is_fixed(result.changes[0].content))
        prompt = llm.prompts[0]
        self.assertIn("Fix attempt 1 of 5.", prompt)
        self.assertIn("=== src/scenes/StartScene.ts ===\n" + BROKEN_START.rstrip(), prompt)
        self.assertNotIn("=== src/scenes/GameScene.ts ===", prompt)      # not relevant: content hidden ...
        self.assertIn('"src/scenes/GameScene.ts"', prompt)                # ... but listed in the project tree
        self.assertIn("'default' is not exported", prompt)
        self.assertNotIn("added 25 packages", prompt)                     # compact TestResult, no install log

    def test_repair_then_ok(self):
        rewrite = reply(("src/scenes/StartScene.ts", "update", "\n".join(f"// {i}" for i in range(40)) + "\n"))
        llm = FakeLLM(rewrite, GOOD_REPLY)
        self.assertIsInstance(self.run_fix(llm), FileChangeSet)
        self.assertIn("changed lines", llm.prompts[1])

    def test_node_error_after_failed_repair(self):
        bad = reply(("src/scenes/GameScene.ts", "update", "x\n"))
        result = self.run_fix(FakeLLM(bad, bad))
        self.assertIsInstance(result, NodeError)
        self.assertEqual(result.node, "fixer")

    def test_empty_fix_is_allowed(self):
        self.assertEqual(self.run_fix(FakeLLM('{"changes": []}')).changes, [])

    def test_no_files_written(self):
        before = file_hashes()
        self.run_fix(FakeLLM(GOOD_REPLY))
        self.assertEqual(file_hashes(), before)


class FixerNodeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        project = self.root / "generated/dodge-demo"
        for path, content in PHASER.files.items():
            (project / path).parent.mkdir(parents=True, exist_ok=True)
            (project / path).write_text(content)
        (project / "node_modules/phaser").mkdir(parents=True)
        (project / "node_modules/phaser/index.js").write_text("// not project source\n")

    def tearDown(self):
        self._tmp.cleanup()

    def state(self, **kw) -> GameFactoryState:
        values = dict(user_idea=BLOCK_DODGER_IDEA, game_spec=sample_game_spec(), task_plan=sample_task_plan(),
                      target_dir="generated/dodge-demo", test_result=PHASER.test_result,
                      status=FactoryStatus.TESTS_FAILED)
        return GameFactoryState(**{**values, **kw})

    def test_proposes_fix(self):
        before = file_hashes(self.root)
        llm = FakeLLM(GOOD_REPLY)
        out = fixer_node(self.state(fix_attempts=1), llm=llm, root=self.root)
        self.assertEqual(out["status"], FactoryStatus.FIXING, out.get("error"))
        self.assertEqual(out["fix_attempts"], 2)
        self.assertEqual([c.path for c in out["fix_changes"]], ["src/scenes/StartScene.ts"])
        self.assertIn("Fix attempt 2 of 5.", llm.prompts[0])
        self.assertNotIn("node_modules/phaser/index.js", llm.prompts[0])  # not project source
        self.assertEqual(file_hashes(self.root), before)

    def test_no_llm_call_when_not_fixable(self):
        cases = {
            "passed": (self.state(test_result=TestResult(status="passed")), "nothing to fix"),
            "error": (self.state(test_result=TestResult(status="error", summary="timeout")), "not fixable"),
            "exhausted": (self.state(fix_attempts=5), "fix attempts exhausted (5/5)"),
            "no result": (self.state(test_result=None), "needs test_result"),
            "no target": (self.state(target_dir=None), "no target_dir"),
            "bad target": (self.state(target_dir="../outside"), "cannot read project"),
        }
        for name, (state, needle) in cases.items():
            with self.subTest(case=name):
                llm = FakeLLM()
                out = fixer_node(state, llm=llm, root=self.root)
                self.assertEqual(out["status"], FactoryStatus.ERROR)
                self.assertIn(needle, out["error"])
                self.assertEqual(llm.prompts, [])

    def test_no_safe_fix_counts_as_attempt(self):
        out = fixer_node(self.state(), llm=FakeLLM('{"changes": []}'), root=self.root)
        self.assertEqual(out["status"], FactoryStatus.ERROR)
        self.assertIn("no safe fix", out["error"])
        self.assertEqual(out["fix_attempts"], 1)

    def test_node_error_counts_as_attempt(self):
        bad = reply(("src/scenes/GameScene.ts", "update", "x\n"))
        out = fixer_node(self.state(), llm=FakeLLM(bad, bad), root=self.root)
        self.assertEqual(out["status"], FactoryStatus.ERROR)
        self.assertIn("attempt 1:", out["error"])
        self.assertEqual(out["fix_attempts"], 1)


def run_script(argv, llm):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = run_fixer_dry_run.main(["run_fixer_dry_run.py", *argv], llm=llm)
    return code, out.getvalue()


class ScriptTest(unittest.TestCase):
    def test_plausible_fix(self):
        code, out = run_script(["--case", "phaser-default"], FakeLLM(GOOD_REPLY))
        self.assertEqual(code, 0, out)
        for needle in ["-import Phaser from 'phaser';", "+import * as Phaser from 'phaser';",
                       "plausible fix (culprit src/scenes/StartScene.ts fixed): yes", "filesystem unchanged: yes"]:
            self.assertIn(needle, out)

    def test_implausible_fix(self):
        wrong = reply(("src/main.ts", "update", BASE_FILES["src/main.ts"] + "export const touched = true;\n"))
        code, out = run_script(["--case", "phaser-default"], FakeLLM(wrong))
        self.assertEqual(code, 1)
        self.assertIn("plausible fix (culprit src/scenes/StartScene.ts fixed): NO", out)

    def test_no_fix_and_json(self):
        self.assertEqual(run_script(["--case", "import-case"], FakeLLM('{"changes": []}'))[0], 1)
        code, out = run_script(["--json"], FakeLLM(GOOD_REPLY))
        self.assertEqual(code, 0)
        self.assertEqual(len(FileChangeSet.model_validate_json(out).changes), 1)


@unittest.skipUnless(os.environ.get("RUN_OLLAMA_TESTS") == "1", "set RUN_OLLAMA_TESTS=1 (needs `ollama serve`)")
class FixerLLMTest(unittest.TestCase):
    def test_real_model_fixes_synthetic_cases(self):
        for name, make in CASES.items():
            case = make()
            with self.subTest(case=name):
                result = fix(case.test_result, case.files, sample_game_spec(), sample_task_plan())
                self.assertIsInstance(result, FileChangeSet, getattr(result, "validation_errors", result))
                new = {c.path: c.content for c in result.changes}
                self.assertIn(case.culprit, new, [c.path for c in result.changes])
                self.assertTrue(case.is_fixed(new[case.culprit]), new[case.culprit])


if __name__ == "__main__":
    unittest.main()
