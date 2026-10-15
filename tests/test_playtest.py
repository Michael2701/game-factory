"""M21c playtest plan: normalization, consistency with the spec, derived hook contract, planner + reviewer."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agents.generators.acceptance import acceptance_spec  # noqa: E402
from agents.generators.phaser_template import spec_base  # noqa: E402
from agents.generators.playtest import (  # noqa: E402
    check_playtest,
    control_keys,
    derive_playtest,
    describe,
    hook_contract,
    normalize_key,
    normalize_playtest,
)
from agents.nodes.planner import plan_game  # noqa: E402
from agents.nodes.reviewer import check_review, review_facts  # noqa: E402
from agents.schemas import Control, GameSpec, ReviewResult, TestResult  # noqa: E402
from agents.schemas.examples import sample_game_spec  # noqa: E402
from fakes import FakeLLM  # noqa: E402
from test_acceptance import CLICKER, MEMORY, SNAKE  # noqa: E402
from test_reviewer import review_json  # noqa: E402

DODGER = sample_game_spec()


def with_playtest(spec: GameSpec, **changes) -> GameSpec:
    return spec.model_copy(update={"playtest": spec.playtest.model_copy(update=changes)})


class NormalizeTest(unittest.TestCase):
    def test_keys(self):
        cases = {"ArrowLeft": "ArrowLeft", "Left Arrow": "ArrowLeft", "left": "ArrowLeft", "←": "ArrowLeft",
                 "arrow up": "ArrowUp", "Space": "Space", "spacebar": "Space", "W": "KeyW", "key a": "KeyA",
                 "Enter": "Enter", "Mouse click": "Click", "MouseLeft": "Click", "Tap": "Click", "1": "Digit1"}
        for raw, key in cases.items():
            self.assertEqual(normalize_key(raw), key, raw)
        self.assertIsNone(normalize_key("telepathy"))

    def test_control_lists(self):
        spec = DODGER.model_copy(update={"controls": [Control(input="ArrowLeft / ArrowRight", action="move"),
                                                      Control(input="Space", action="jump")]})
        self.assertEqual(control_keys(spec), {"ArrowLeft", "ArrowRight", "Space"})

    def test_playtest_inputs_are_normalized(self):
        spec = DODGER.model_copy(update={"playtest": DODGER.playtest.model_copy(update={"inputs": [
            DODGER.playtest.inputs[0].model_copy(update={"input": "Left Arrow"})]})})
        self.assertEqual(normalize_playtest(spec).playtest.inputs[0].input, "ArrowLeft")


class CheckTest(unittest.TestCase):
    def test_valid_specs(self):
        for spec in (DODGER, CLICKER, SNAKE, MEMORY):
            self.assertEqual(check_playtest(spec), [], spec.title)

    def test_problems(self):
        self.assertIn("playtest: required", check_playtest(DODGER.model_copy(update={"playtest": None}))[0])
        bad_key = with_playtest(DODGER, inputs=[DODGER.playtest.inputs[0].model_copy(update={"input": "Space"})])
        self.assertTrue(any("not one of the game's controls" in e for e in check_playtest(bad_key)))
        no_avatar = with_playtest(DODGER, player=None)
        self.assertTrue(any("needs an avatar" in e for e in check_playtest(no_avatar)))
        wrong_time = with_playtest(DODGER, round_end=DODGER.playtest.round_end.model_copy(update={"seconds": 30}))
        self.assertTrue(any("does not match the win/lose conditions ([60] seconds)" in e
                            for e in check_playtest(wrong_time)))
        no_seconds = with_playtest(DODGER, round_end=DODGER.playtest.round_end.model_copy(update={"seconds": None}))
        self.assertTrue(any("seconds: required" in e for e in check_playtest(no_seconds)))

    def test_derived_playtest_for_old_specs(self):
        pt = derive_playtest(DODGER.model_copy(update={"playtest": None}))
        self.assertEqual([i.input for i in pt.inputs], ["ArrowLeft", "ArrowRight"])
        self.assertEqual(pt.round_end.seconds, 60)


class ContractTest(unittest.TestCase):
    def test_contract_depends_on_the_game(self):
        base = {"__GAME_STATE__", "__TEST_API__", "scene", "result", "texts", "objects", "startGame", "skipTime",
                "finishRound"}
        self.assertEqual(set(hook_contract(DODGER)) - base, {"player", "difficulty"})
        self.assertEqual(set(hook_contract(CLICKER)) - base, {"score", "clickTarget"})
        self.assertEqual(set(hook_contract(MEMORY)) - base, {"clickTarget"})
        self.assertEqual(set(hook_contract(SNAKE)) - base, {"player", "score"})

    def test_describe(self):
        text = describe(CLICKER)
        self.assertIn("a real click at __GAME_STATE__.clickTarget must cause: score up", text)
        self.assertIn("skipTime(30)", text)
        self.assertNotIn("avatar", text)
        self.assertIn("finishRound('lose')", describe(MEMORY))


class PlannerTest(unittest.TestCase):
    def test_spec_without_playtest_is_repaired(self):
        missing = DODGER.model_copy(update={"playtest": None}).model_dump_json()
        llm = FakeLLM(missing, DODGER.model_dump_json())
        result = plan_game("dodge falling blocks", llm=llm)
        self.assertIsInstance(result, GameSpec)
        self.assertIn("playtest: required", llm.prompts[1])  # the repair prompt says what is missing

    def test_keys_are_normalized_before_the_check(self):
        data = DODGER.model_dump()
        data["playtest"]["inputs"][0]["input"] = "left arrow"
        result = plan_game("dodge falling blocks", llm=FakeLLM(GameSpec.model_validate(data).model_dump_json()))
        self.assertEqual(result.playtest.inputs[0].input, "ArrowLeft")


class ReviewerNotApplicableTest(unittest.TestCase):
    def test_checks_without_a_step_must_pass_as_not_applicable(self):
        files = spec_base("phaser-vite-template", MEMORY)  # no HUD, no difficulty in this game's playtest
        files["tests/acceptance.spec.ts"] = acceptance_spec(MEMORY)
        files["src/scenes/GameScene.ts"] += "\n// flash(this)\n"
        passed = TestResult(status="passed", summary="tests 4/4 passed")
        facts = review_facts(files, passed)
        self.assertEqual(sorted(facts["quality_not_applicable"]), ["difficulty_ramps", "hud_visible"])
        bad = ReviewResult.model_validate_json(review_json("needs_changes", failed=("difficulty_ramps",)))
        errors = check_review(bad, facts, files)
        self.assertTrue(any("checks.difficulty_ramps: passed must be true — not applicable" in e for e in errors),
                        errors)


if __name__ == "__main__":
    unittest.main()
