"""M17 reviewer node: facts, files summary, semantic check, repair flow, node, runner.

Deterministic tests use FakeLLM. Gated (RUN_OLLAMA_TESTS=1): the real model reviews the
passing fixture project and a variant without a restart (UX issue).
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agents.fixtures.broken_projects import BASE_FILES, CASES  # noqa: E402
from agents.nodes import reviewer, test_runner  # noqa: E402
from agents.nodes.reviewer import (  # noqa: E402
    REVIEW_CHECKS,
    check_review,
    files_summary,
    review,
    review_facts,
    reviewer_node,
)
from agents.prompts import load_prompt  # noqa: E402
from agents.schemas import FactoryStatus, GameFactoryState, NodeError, ReviewResult, TestResult  # noqa: E402
from agents.schemas.examples import sample_game_spec  # noqa: E402
from fakes import FakeLLM  # noqa: E402
from scripts import run_reviewer  # noqa: E402

TARGET = "generated/demo"
PASSED = TestResult(status="passed", summary="install ok · build ok · tests 3/3 passed")
TESTS_FAILED = TestResult(status="failed", summary="install ok · build ok · tests 2/3 passed",
                          failures=[{"name": "game.spec.ts › wins", "message": "timeout"}])
BUILD_FAILED = CASES["missing-file"]().test_result


def review_json(verdict: str = "approve", failed: tuple[str, ...] = (), issues: list[str] | None = None,
                note: str = "ok") -> str:
    """A ReviewResult reply: every check passes except `failed`."""
    if issues is None:
        issues = [] if verdict == "approve" else ["src/main.ts: something is wrong"]
    return json.dumps({
        "verdict": verdict,
        "checks": [{"name": n, "passed": n not in failed, "note": note} for n in REVIEW_CHECKS],
        "issues": issues,
        "suggestions": ["Show the remaining time"],
        "summary": f"Review: {verdict}.",
    })


APPROVE = review_json()
REJECT_BUILD = review_json("reject", failed=("browser_game_suitable",))
NEEDS_CHANGES = review_json("needs_changes", failed=("no_obvious_ux_issues",))


def parse(text: str) -> ReviewResult:
    return ReviewResult.model_validate_json(text)


def example_json() -> str:
    text = load_prompt("reviewer")
    return text.split("## Example output", 1)[1].split("```json", 1)[1].split("```", 1)[0]


class FactsTest(unittest.TestCase):
    def test_passing_fixture(self):
        facts = review_facts(BASE_FILES, PASSED)
        self.assertTrue(facts["build_ok"])
        self.assertTrue(facts["test_hooks_present"])
        self.assertEqual(facts["tests_passed"], "3/3")
        self.assertEqual(facts["test_count"], 3)
        self.assertEqual(facts["scene_files"], ["src/scenes/GameScene.ts", "src/scenes/StartScene.ts"])
        self.assertEqual(facts["scenes_outside_src_scenes"], [])
        self.assertEqual(facts["stray_files"], [])

    def test_build_failed(self):
        facts = review_facts(BASE_FILES, BUILD_FAILED)
        self.assertIs(facts["build_ok"], False)
        self.assertIsNone(facts["tests_passed"])
        self.assertFalse(facts["tests_ran"])

    def test_build_not_run(self):
        self.assertIsNone(review_facts(BASE_FILES, TestResult(status="failed", summary="install failed"))["build_ok"])

    def test_hooks_missing_in_tests(self):
        files = {**BASE_FILES, "tests/game.spec.ts": "import { test } from '@playwright/test';\ntest('a', () => {});\n"}
        facts = review_facts(files, PASSED)
        self.assertFalse(facts["test_hooks_present"])
        self.assertEqual(facts["hooks_used_in_tests"], {"__GAME_STATE__": False, "__TEST_API__": False})
        self.assertTrue(all(facts["hooks_defined_in_src"].values()))

    def test_layout(self):
        files = {**BASE_FILES, "src/Extra.ts": "class X extends Phaser.Scene {}\n", "notes.js": "x\n"}
        facts = review_facts(files, PASSED)
        self.assertEqual(facts["scenes_outside_src_scenes"], ["src/Extra.ts"])
        self.assertEqual(facts["stray_files"], ["notes.js"])


class FilesSummaryTest(unittest.TestCase):
    def test_tree_and_contents(self):
        text = files_summary(BASE_FILES)
        for path in BASE_FILES:
            self.assertIn(path, text)
        self.assertIn("=== src/main.ts ===", text)
        self.assertNotIn("omitted", text)

    def test_budget_keeps_tree_and_src_first(self):
        files = {"src/main.ts": "a\n" * 50, "tests/game.spec.ts": "b\n" * 50, "package.json": "{}"}
        text = files_summary(files, max_chars=120)
        self.assertIn("=== src/main.ts ===", text)
        self.assertNotIn("=== tests/game.spec.ts ===", text)
        self.assertIn("tests/game.spec.ts  (50 lines)", text)
        self.assertIn("content omitted for size: tests/game.spec.ts", text)


class CheckReviewTest(unittest.TestCase):
    def errors(self, reply: str, result: TestResult = PASSED, files: dict | None = None) -> list[str]:
        files = files or BASE_FILES
        return check_review(parse(reply), review_facts(files, result), files)

    def test_valid_reviews(self):
        self.assertEqual(self.errors(APPROVE), [])
        self.assertEqual(self.errors(NEEDS_CHANGES), [])
        self.assertEqual(self.errors(REJECT_BUILD, BUILD_FAILED), [])
        self.assertEqual(self.errors(review_json("needs_changes", failed=("testable",)), TESTS_FAILED), [])

    def test_prompt_example_passes(self):
        files = {**BASE_FILES, "src/scenes/WordScene.ts": "export class WordScene {}\n",
                 "src/hooks.ts": "export {};\n"}
        self.assertEqual(check_review(parse(example_json()), review_facts(files, PASSED), files), [])

    def test_prompt_example_copied_verbatim_is_caught(self):
        """qwen tends to copy the example; its file names are not in a real project."""
        errors = self.errors(example_json())
        self.assertTrue(any("names files that are not in the project" in e for e in errors), errors)

    def test_check_names_and_order(self):
        data = json.loads(APPROVE)
        data["checks"] = data["checks"][::-1]
        self.assertIn("checks: expected exactly", self.errors(json.dumps(data))[0])
        data["checks"] = data["checks"][1:]
        self.assertIn("checks: expected exactly", self.errors(json.dumps(data))[0])

    def test_approve_needs_all_checks_and_passed_tests(self):
        errors = self.errors(review_json("approve", failed=("no_obvious_ux_issues",)))
        self.assertTrue(any("requires every check to pass" in e for e in errors), errors)
        errors = self.errors(APPROVE, TESTS_FAILED)
        self.assertTrue(any("requires passed tests" in e for e in errors), errors)

    def test_all_passed_must_approve(self):
        errors = self.errors(review_json("needs_changes"))
        self.assertTrue(any("must be 'approve'" in e for e in errors), errors)

    def test_build_failed_rules(self):
        errors = self.errors(review_json("needs_changes", failed=("testable",)), BUILD_FAILED)
        self.assertTrue(any("checks.browser_game_suitable: passed must be false" in e for e in errors), errors)
        self.assertTrue(any("verdict must be 'reject'" in e for e in errors), errors)

    def test_hooks_must_match_facts(self):
        errors = self.errors(review_json("needs_changes", failed=("test_hooks_present",)))
        self.assertTrue(any("checks.test_hooks_present: passed must be true" in e for e in errors), errors)
        files = {**BASE_FILES, "src/testHooks.ts": "export {};\n"}
        errors = self.errors(APPROVE, files=files)
        self.assertTrue(any("checks.test_hooks_present: passed must be false" in e for e in errors), errors)

    def test_layout_must_match_facts(self):
        files = {**BASE_FILES, "notes.js": "x\n"}
        errors = self.errors(APPROVE, files=files)
        self.assertTrue(any("checks.files_organized: passed must be false" in e for e in errors), errors)

    def test_non_approve_needs_issues(self):
        errors = self.errors(review_json("needs_changes", failed=("no_obvious_ux_issues",), issues=[]))
        self.assertTrue(any(e.startswith("issues: verdict 'needs_changes'") for e in errors), errors)

    def test_unknown_files_in_issues_and_notes(self):
        errors = self.errors(review_json("needs_changes", failed=("no_obvious_ux_issues",),
                                         issues=["src/scenes/GameOverScene.ts: no restart"]))
        self.assertTrue(any(e.startswith("issues.0: names files") for e in errors), errors)
        errors = self.errors(review_json(note="see src/ghost.ts"))
        self.assertTrue(any(e.startswith("checks.scope_small.note: names files") for e in errors), errors)

    def test_missing_file_may_be_named(self):
        reply = review_json("needs_changes", failed=("no_obvious_ux_issues",),
                            issues=["src/scenes/GameOverScene.ts: missing, so there is no restart"])
        self.assertEqual(self.errors(reply), [])

    def test_suggestions_may_name_new_files(self):
        data = json.loads(APPROVE)
        data["suggestions"] = ["Add src/scenes/PauseScene.ts"]
        self.assertEqual(self.errors(json.dumps(data)), [])


class ReviewTest(unittest.TestCase):
    def test_valid_first_try_and_prompt(self):
        llm = FakeLLM(APPROVE)
        result = review(sample_game_spec(), BASE_FILES, PASSED, llm=llm)
        self.assertIsInstance(result, ReviewResult)
        self.assertEqual(result.verdict, "approve")
        prompt = llm.prompts[0]
        for needle in ["=== src/scenes/GameScene.ts ===", '"test_hooks_present": true', "3/3 passed",
                       sample_game_spec().win_condition]:
            self.assertIn(needle, prompt)

    def test_fenced_output(self):
        result = review(sample_game_spec(), BASE_FILES, PASSED, llm=FakeLLM(f"Here:\n```json\n{APPROVE}\n```"))
        self.assertIsInstance(result, ReviewResult)

    def test_repair_success(self):
        llm = FakeLLM(review_json("approve"), REJECT_BUILD)
        result = review(sample_game_spec(), BASE_FILES, BUILD_FAILED, llm=llm)
        self.assertIsInstance(result, ReviewResult)
        self.assertEqual(result.verdict, "reject")
        self.assertEqual(len(llm.prompts), 2)
        self.assertIn("verdict must be 'reject'", llm.prompts[1])

    def test_repair_failure(self):
        bad = review_json("approve")
        result = review(sample_game_spec(), BASE_FILES, BUILD_FAILED, llm=FakeLLM(bad, bad))
        self.assertIsInstance(result, NodeError)
        self.assertEqual(result.attempts, 2)
        self.assertTrue(result.validation_errors)

    def test_llm_exception(self):
        result = review(sample_game_spec(), BASE_FILES, PASSED, llm=FakeLLM(ConnectionError("ollama down")))
        self.assertIsInstance(result, NodeError)
        self.assertIn("LLM call failed", result.message)

    def test_empty_project_no_llm_call(self):
        llm = FakeLLM()
        self.assertIsInstance(review(sample_game_spec(), {}, PASSED, llm=llm), NodeError)
        self.assertEqual(llm.prompts, [])


class TempRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        for path, content in BASE_FILES.items():
            (self.root / TARGET / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / TARGET / path).write_text(content)

    def tearDown(self):
        self._tmp.cleanup()

    def snapshot(self) -> dict[str, str]:
        return {str(p.relative_to(self.root)): p.read_text() for p in self.root.rglob("*") if p.is_file()}


class ReviewerNodeTest(TempRoot):
    def state(self, **update) -> GameFactoryState:
        base = GameFactoryState(user_idea="demo", game_spec=sample_game_spec(), target_dir=TARGET,
                                test_result=PASSED, status=FactoryStatus.TESTS_PASSED)
        return base.model_copy(update=update)

    def test_sets_review_keeps_status_writes_nothing(self):
        before = self.snapshot()
        out = reviewer_node(self.state(), llm=FakeLLM(APPROVE), root=self.root)
        self.assertEqual(out["review_result"].verdict, "approve")
        self.assertNotIn("status", out)
        self.assertIsNone(out["error"])
        self.assertEqual(self.snapshot(), before)

    def test_missing_input_no_llm_call(self):
        cases = {"no spec": {"game_spec": None}, "no test result": {"test_result": None},
                 "no target": {"target_dir": None}, "outside": {"target_dir": "../etc"}}
        for name, update in cases.items():
            with self.subTest(name):
                llm = FakeLLM()
                out = reviewer_node(self.state(**update), llm=llm, root=self.root)
                self.assertEqual(out["status"], FactoryStatus.ERROR)
                self.assertTrue(out["error"].startswith("reviewer: "), out["error"])
                self.assertEqual(llm.prompts, [])

    def test_node_error(self):
        out = reviewer_node(self.state(), llm=FakeLLM("nope", "nope"), root=self.root)
        self.assertEqual(out["status"], FactoryStatus.ERROR)
        self.assertIn("not a valid ReviewResult", out["error"])


def run_script(argv, llm, root):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = run_reviewer.main(["run_reviewer.py", *argv], llm=llm, root=root)
    return code, out.getvalue()


class ScriptTest(TempRoot):
    def test_review_and_exit_codes(self):
        with mock.patch.object(test_runner, "run_project_checks", lambda *a, **k: PASSED):
            code, out = run_script(["--project-dir", TARGET], FakeLLM(APPROVE), self.root)
        self.assertEqual(code, 0, out)
        for needle in ["=== REVIEW ===", "verdict: approve", "PASS  test_hooks_present", "files changed by the reviewer: 0"]:
            self.assertIn(needle, out)

    def test_json_and_spec_file(self):
        (self.root / "spec.json").write_text(sample_game_spec().model_dump_json())
        with mock.patch.object(test_runner, "run_project_checks", lambda *a, **k: PASSED):
            code, out = run_script(["--project-dir", TARGET, "--spec", str(self.root / "spec.json"), "--json"],
                                   FakeLLM(NEEDS_CHANGES), self.root)
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["verdict"], "needs_changes")

    def test_node_error_exit_1(self):
        with mock.patch.object(test_runner, "run_project_checks", lambda *a, **k: PASSED):
            code, out = run_script(["--project-dir", TARGET], FakeLLM("x", "x"), self.root)
        self.assertEqual(code, 1, out)

    def test_usage_errors_exit_2(self):
        for argv in (["--project-dir", "agents"], ["--project-dir", "generated/missing"],
                     ["--project-dir", TARGET, "--spec", "missing.json"]):
            with self.subTest(argv=argv):
                code, _ = run_script(argv, FakeLLM(), self.root)
                self.assertEqual(code, 2)


@unittest.skipUnless(os.environ.get("RUN_OLLAMA_TESTS") == "1", "set RUN_OLLAMA_TESTS=1 (needs `ollama serve`)")
class RealModelTest(unittest.TestCase):
    def test_passing_fixture(self):
        result = review(sample_game_spec(), BASE_FILES, PASSED)
        self.assertIsInstance(result, ReviewResult, getattr(result, "model_dump_json", lambda: "")())
        self.assertEqual([c.name for c in result.checks], list(REVIEW_CHECKS))
        self.assertTrue(next(c for c in result.checks if c.name == "test_hooks_present").passed)

    def test_build_failure_is_rejected(self):
        result = review(sample_game_spec(), CASES["missing-file"]().files, BUILD_FAILED)
        self.assertIsInstance(result, ReviewResult, getattr(result, "model_dump_json", lambda: "")())
        self.assertEqual(result.verdict, "reject")


if __name__ == "__main__":
    unittest.main()
