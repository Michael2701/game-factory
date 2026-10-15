"""M22 quality bar: reviewer game-feel checks driven by acceptance facts, template look helpers."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agents.generators.acceptance import acceptance_spec  # noqa: E402
from agents.generators.phaser_template import controls_hint, instantiate, spec_base  # noqa: E402
from agents.nodes.reviewer import REVIEW_CHECKS, check_review, review_facts  # noqa: E402
from agents.schemas import ReviewResult, TestFailure, TestResult  # noqa: E402
from agents.schemas.examples import sample_game_spec  # noqa: E402
from test_reviewer import review_json  # noqa: E402

SPEC = sample_game_spec()
QUALITY = ("hud_visible", "difficulty_ramps", "feedback_on_events", "start_screen_explains_controls")


def project(feedback: bool = True) -> dict[str, str]:
    files = spec_base("phaser-vite-template", SPEC)
    files["tests/acceptance.spec.ts"] = acceptance_spec(SPEC)  # M21c: its steps decide which checks apply
    scene = "this.player = this.add.rectangle(1, 2, 3, 4);\n" + ("flash(this);\n" if feedback else "")
    files["src/scenes/GameScene.ts"] = files["src/scenes/GameScene.ts"].replace(
        "    // The game goes here", "    " + scene + "    // The game goes here")
    return files


class ReviewerQualityTest(unittest.TestCase):
    def errors(self, reply: str, result: TestResult, files: dict[str, str]) -> list[str]:
        return check_review(ReviewResult.model_validate_json(reply), review_facts(files, result), files)

    def test_checks_and_facts(self):
        self.assertEqual(REVIEW_CHECKS[-4:], QUALITY)
        facts = review_facts(project(), TestResult(status="passed", summary="tests 11/11 passed"))
        self.assertTrue(facts["quality_bar"])
        self.assertTrue(facts["acceptance_passed"])
        self.assertTrue(facts["feedback_code"])
        self.assertEqual(facts["quality_failures"], {})

    def test_acceptance_failure_blocks_approve(self):
        failed = TestResult(status="failed", summary="tests 10/11 passed", failures=[TestFailure(
            name="acceptance.spec.ts › acceptance", message="Error: [hud_visible] the HUD did not change after 5 "
                                                            "seconds of game time; it shows: Time: 60")])
        facts = review_facts(project(), failed)
        self.assertIn("hud_visible", facts["quality_failures"])
        errors = self.errors(review_json("needs_changes"), failed, project())  # model says hud passed
        self.assertTrue(any("checks.hud_visible: passed must be false" in e for e in errors), errors)
        # the spec stops at hud_visible: the start screen before it is proven, the steps after it are not (M21b)
        self.assertEqual(facts["quality_proven"], ["start_screen_explains_controls"])
        self.assertEqual(facts["quality_unverified"], ["difficulty_ramps", "feedback_on_events"])
        ok = self.errors(review_json("needs_changes", failed=("hud_visible", "difficulty_ramps", "feedback_on_events")),
                         failed, project())
        self.assertEqual(ok, [])

    def test_untagged_acceptance_failure_verifies_nothing(self):
        # r10: skipTime threw a TypeError before any quality step; the model still marked all four as passed
        failed = TestResult(status="failed", summary="tests 0/4 passed", failures=[TestFailure(
            name="acceptance.spec.ts › acceptance", message="Error: page.evaluate: TypeError: this.time.add is "
                                                            "not a function")])
        facts = review_facts(project(), failed)
        self.assertFalse(facts["acceptance_passed"])
        self.assertEqual(facts["quality_proven"], [])
        self.assertEqual(sorted(facts["quality_unverified"]), sorted(QUALITY))
        errors = self.errors(review_json("needs_changes"), failed, project())
        for name in QUALITY:
            self.assertTrue(any(f"checks.{name}: passed must be false — not verified" in e for e in errors), errors)
        self.assertEqual(self.errors(review_json("needs_changes", failed=QUALITY), failed, project()), [])

    def test_other_test_failing_does_not_unprove_acceptance(self):
        failed = TestResult(status="failed", summary="tests 10/11 passed", failures=[TestFailure(
            name="game.spec.ts › win", message="Error: timeout")])
        facts = review_facts(project(), failed)
        self.assertTrue(facts["acceptance_passed"])
        self.assertEqual(facts["quality_unverified"], [])

    def test_passed_acceptance_proves_the_quality_checks(self):
        passed = TestResult(status="passed", summary="tests 11/11 passed")
        errors = self.errors(review_json("needs_changes", failed=("difficulty_ramps",)), passed, project())
        self.assertTrue(any("checks.difficulty_ramps: passed must be true" in e for e in errors), errors)

    def test_no_feedback_code_fails_feedback(self):
        passed = TestResult(status="passed", summary="tests 11/11 passed")
        errors = self.errors(review_json(), passed, project(feedback=False))
        self.assertTrue(any("checks.feedback_on_events: passed must be false" in e for e in errors), errors)

    def test_restart_failure_is_a_ux_issue(self):
        failed = TestResult(status="failed", failures=[TestFailure(
            name="acceptance", message="[restart] a click on the game-over screen did not start a new round")])
        errors = self.errors(review_json("needs_changes", failed=("hud_visible",)), failed, project())
        self.assertTrue(any("checks.no_obvious_ux_issues: passed must be false" in e for e in errors), errors)

    def test_old_projects_are_judged_by_the_model(self):
        old = {"src/main.ts": "window.__GAME_STATE__ = {}; window.__TEST_API__ = {};",
               "src/scenes/GameScene.ts": "class GameScene extends Phaser.Scene {}",
               "tests/game.spec.ts": "__GAME_STATE__ __TEST_API__"}
        passed = TestResult(status="passed", summary="tests 3/3 passed")
        self.assertFalse(review_facts(old, passed)["quality_bar"])
        self.assertEqual(self.errors(review_json(), passed, old), [])  # no ui.ts: no quality facts enforced


class TemplateLookTest(unittest.TestCase):
    def test_start_screen_title_and_controls(self):
        self.assertEqual(controls_hint(SPEC), "← move left · → move right")
        start = spec_base("phaser-vite-template", SPEC)["src/scenes/StartScene.ts"]
        self.assertIn("title(this, 'Block Dodger');", start)
        self.assertIn("hint(this, '← move left · → move right');", start)
        self.assertIn("this.input.once('pointerdown'", start)

    def test_ui_helpers_and_hooks(self):
        files = instantiate("x", "X")
        for name in ("PALETTE", "function title", "function hint", "function hud", "function flash",
                     "function shake"):
            self.assertIn(name, files["src/ui.ts"])
        self.assertIn("hudText = hud(this, '')", files["src/scenes/GameScene.ts"])
        self.assertIn("endGame(result", files["src/scenes/GameScene.ts"])
        self.assertIn("Click to play again", files["src/scenes/GameOverScene.ts"])  # M21c: in the template
        for hook in ("get player()", "get score()", "get difficulty()", "get clickTarget()", "get texts()",
                     "get objects()", "finishRound("):
            self.assertIn(hook, files["src/testHooks.ts"])
        for word in ("difficulty = 1", "hazard", "skipTime(60)", "playerX"):  # nothing genre-specific
            self.assertNotIn(word, "".join(files[p] for p in ("src/scenes/GameScene.ts", "src/ui.ts",
                                                               "src/testHooks.ts")))


class PlannerQualityBarTest(unittest.TestCase):
    def test_quality_bar_added_by_code(self):
        from agents.nodes.planner import DIFFICULTY_ITEM, QUALITY_BAR, with_quality_bar
        spec = with_quality_bar(SPEC)  # the dodger's playtest says it gets harder
        self.assertEqual(spec.quality_requirements, [*QUALITY_BAR, DIFFICULTY_ITEM])
        self.assertEqual(with_quality_bar(spec), spec)  # idempotent
        calm = SPEC.model_copy(update={"playtest": SPEC.playtest.model_copy(update={"difficulty_ramps": False})})
        self.assertEqual(with_quality_bar(calm).quality_requirements, list(QUALITY_BAR))  # M21c: per game
        self.assertFalse(any("hazard" in q for q in QUALITY_BAR))
        from agents.prompts import load_prompt
        self.assertIn("small but complete", load_prompt("planner"))
        self.assertNotIn("smallest version", load_prompt("planner"))


class FromDecisionTest(unittest.TestCase):
    """M22: the human note of `decide.py changes` becomes the fixer's task."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "generated").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, argv, llm):
        import contextlib
        import io
        from unittest import mock
        from agents.nodes import test_runner
        from scripts import run_fix_loop
        from test_fix_loop import FakeChecks
        out = io.StringIO()
        with mock.patch.object(test_runner, "run_project_checks", FakeChecks("passed")), \
                contextlib.redirect_stdout(out):
            code = run_fix_loop.main(["run_fix_loop.py", *argv], llm=llm, root=self.root)
        return code, out.getvalue()

    def gated_project(self, decision: str | None) -> str:
        from agents.nodes.human_gate import decide, human_gate_node
        from agents.schemas import FactoryStatus, GameFactoryState, ReviewResult
        from agents.tools.apply_changes import apply_changes
        from agents.generators.phaser_template import template_changes
        from test_reviewer import APPROVE
        target = "generated/game"
        apply_changes(template_changes("game", "Game"), target, apply=True, root=self.root)
        state = GameFactoryState(user_idea="x", game_spec=SPEC, template="phaser-vite-template", target_dir=target,
                                 test_result=TestResult(status="passed", summary="ok"),
                                 review_result=ReviewResult.model_validate_json(APPROVE),
                                 status=FactoryStatus.TESTS_PASSED)
        state = state.model_copy(update=human_gate_node(state, root=self.root))
        if decision:
            from agents.nodes.human_gate import save_state
            save_state(decide(state, decision, "show the score in the top-right corner"), self.root)
        return target

    def test_note_reaches_the_fixer_and_the_loop_ends_at_the_gate(self):
        from fakes import FakeLLM
        from test_reviewer import review_json
        target = self.gated_project("needs_changes")
        scene = (self.root / target / "src/scenes/GameScene.ts").read_text()
        fix = json.dumps({"changes": [{"path": "src/scenes/GameScene.ts", "operation": "update",
                                       "content": scene.replace("difficulty = 1;", "difficulty = 1; // score",
                                                                1).replace("hud(this, '')", "hud(this, 'Score: 0')"),
                                       "reason": "show the score"}]})
        llm = FakeLLM(fix, review_json("needs_changes", failed=("feedback_on_events",)))
        code, out = self.run_script(["--project-dir", target, "--from-decision"], llm)
        self.assertIn("human note for the fixer: show the score in the top-right corner", out)
        self.assertIn("A human played the game and asked for: show the score in the top-right corner", llm.prompts[0])
        self.assertTrue(llm.prompts[0].startswith("# Fixer"))  # the loop started at the fixer
        self.assertIn("hud(this, 'Score: 0')", (self.root / target / "src/scenes/GameScene.ts").read_text())
        self.assertIn("status: needs_human_review", out)

    def test_refusals(self):
        from fakes import FakeLLM
        target = self.gated_project(None)  # gate reached, but no decision yet
        code, out = self.run_script(["--project-dir", target, "--from-decision"], FakeLLM())
        self.assertEqual(code, 2, out)
        self.assertIn("no 'changes' decision with a note", out)
        import contextlib
        import io
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_script(["--case", "two-bugs", "--from-decision"], FakeLLM())


if __name__ == "__main__":
    unittest.main()
