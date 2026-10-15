"""Acceptance spec generator (M21; per game since M21c): real input only, hooks only for state and time
control, steps chosen by the game's playtest plan — for any genre, not one kind of game."""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.generators.acceptance import ACCEPTANCE_FILE, ACCEPTANCE_STEPS, acceptance_spec  # noqa: E402
from agents.schemas import GameSpec  # noqa: E402
from agents.schemas.examples import sample_game_spec  # noqa: E402

DODGER = sample_game_spec()


def spec(title, controls, playtest, win="Win.", lose="Lose.") -> GameSpec:
    return GameSpec.model_validate({
        "title": title, "slug": re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"), "genre": "g",
        "core_loop": "c", "scenes": [{"name": "GameScene", "purpose": "p"}],
        "controls": [{"input": i, "action": "a"} for i in controls], "win_condition": win, "lose_condition": lose,
        "test_requirements": ["t"], "playtest": playtest})


CLICKER = spec("Target Pop", ["Click"], {
    "player": None, "inputs": [{"input": "Click", "expect": "score_up"}], "moves_on_its_own": False,
    "hud": "input", "difficulty_ramps": False, "round_end": {"by": "timer", "seconds": 30}},
    win="Score 15 points within 30 seconds.", lose="The 30 second timer runs out.")
JUMPER = spec("Hop Over", ["Space"], {
    "player": {"moves_by_itself": False}, "inputs": [{"input": "Space", "expect": "player_up"}],
    "moves_on_its_own": True, "hud": "time", "difficulty_ramps": True, "round_end": {"by": "hook"}})
SNAKE = spec("Grid Snake", ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"], {
    "player": {"moves_by_itself": True}, "inputs": [{"input": "ArrowUp", "expect": "player_up"},
                                                    {"input": "ArrowLeft", "expect": "player_left"}],
    "moves_on_its_own": True, "hud": "input", "difficulty_ramps": False, "round_end": {"by": "hook"}})
MEMORY = spec("Pair Finder", ["Click"], {
    "player": None, "inputs": [{"input": "Click", "expect": "state_changes"}], "moves_on_its_own": False,
    "hud": "none", "difficulty_ramps": False, "round_end": {"by": "hook"}})
GENRES = {"dodger": DODGER, "clicker": CLICKER, "jumper": JUMPER, "snake": SNAKE, "memory": MEMORY}


def steps(code: str) -> list[str]:
    return [s for s in ACCEPTANCE_STEPS if f"[{s}]" in code]


class EveryGenreTest(unittest.TestCase):
    def test_common_rules(self):
        for name, game in GENRES.items():
            code = acceptance_spec(game, import_from="./fixtures")
            with self.subTest(name):
                self.assertTrue(code.startswith("import { test, expect } from './fixtures';"))
                self.assertIn("await page.locator('canvas').click();", code)  # real click to start / restart
                self.assertNotIn("startGame", code)  # never the start hook
                self.assertEqual(set(re.findall(r"__TEST_API__\.(\w+)", code)) - {"skipTime", "finishRound"}, set())
                self.assertNotIn("playerX", code)
                self.assertNotIn("hazards", code)
                for shot in ("menu", "gameplay", "gameover"):
                    self.assertIn(f"test-results/acceptance/{shot}.png", code)
                self.assertIn("[restart]", code)
                self.assertIn("[round_end]", code)
                order = [code.index(f"[{s}]") for s in steps(code)]
                self.assertEqual(order, sorted(order))  # steps in ACCEPTANCE_STEPS order
                self.assertIn(game.title.lower(), code)

    def test_steps_follow_the_playtest(self):
        self.assertEqual(steps(acceptance_spec(DODGER)), list(ACCEPTANCE_STEPS))
        self.assertEqual(steps(acceptance_spec(CLICKER)), ["start_screen_explains_controls", "input", "hud_visible",
                                                           "round_end", "feedback_on_events", "restart"])
        self.assertEqual(steps(acceptance_spec(MEMORY)), ["start_screen_explains_controls", "input", "round_end",
                                                          "feedback_on_events", "restart"])
        jumper = acceptance_spec(JUMPER)
        self.assertIn("[world_alive]", jumper)
        self.assertIn("[difficulty_ramps]", jumper)


class InputTest(unittest.TestCase):
    def test_keys_are_pressed_for_real(self):
        code = acceptance_spec(SNAKE)
        for key in ("ArrowUp", "ArrowLeft"):
            self.assertIn(f"await page.keyboard.down('{key}');", code)
            self.assertIn(f"await page.keyboard.up('{key}');", code)
        self.assertIn("now.player.y < before.player.y", code)
        self.assertIn("now.player.x < before.player.x", code)
        self.assertIn("await page.keyboard.down('Space');", acceptance_spec(JUMPER))

    def test_stillness_only_for_an_avatar_that_waits_for_input(self):
        self.assertIn("the avatar moved with no input", acceptance_spec(DODGER))
        self.assertIn("the avatar moved with no input", acceptance_spec(JUMPER))
        self.assertNotIn("the avatar moved with no input", acceptance_spec(SNAKE))  # a snake keeps moving
        self.assertNotIn("__GAME_STATE__?.player", acceptance_spec(CLICKER).split("[input]")[0])

    def test_click_goes_where_the_game_says(self):
        code = acceptance_spec(CLICKER)
        self.assertIn("clickTarget", code)
        self.assertIn("click({ position: target0 })", code)
        self.assertIn("now.score > before.score", code)
        self.assertNotIn("position: { x: 240", code)  # no fixed coordinates
        self.assertIn("JSON.stringify(now) !== JSON.stringify(before)", acceptance_spec(MEMORY))


class TimeTest(unittest.TestCase):
    def test_round_end(self):
        self.assertIn("__TEST_API__.skipTime(60)", acceptance_spec(DODGER))
        self.assertIn("__TEST_API__.skipTime(30)", acceptance_spec(CLICKER))
        for game in (JUMPER, SNAKE, MEMORY):
            self.assertIn("__TEST_API__.finishRound('lose')", acceptance_spec(game))
        self.assertIn("scene === 'GameOverScene'", acceptance_spec(MEMORY))

    def test_skips_stay_inside_a_short_round(self):
        short = spec("Quick", ["Space"], {
            "player": None, "inputs": [{"input": "Space", "expect": "state_changes"}], "moves_on_its_own": False,
            "hud": "time", "difficulty_ramps": True, "round_end": {"by": "timer", "seconds": 10}})
        code = acceptance_spec(short)
        skipped = sum(int(n) for n in re.findall(r"skipTime\((\d+)\)", code.split("[round_end]")[0]))
        self.assertLess(skipped, 10)
        self.assertIn("skipTime(10)", code)

    def test_world_alive_uses_real_time(self):
        code = acceptance_spec(JUMPER)
        alive = code[code.index("[world_alive]"):code.index("[hud_visible]")]
        self.assertNotIn("skipTime", alive)
        self.assertIn("__GAME_STATE__?.objects", alive)


class OldSpecTest(unittest.TestCase):
    def test_spec_without_playtest_gets_a_derived_one(self):
        old = DODGER.model_copy(update={"playtest": None})
        code = acceptance_spec(old)
        self.assertIn("await page.keyboard.down('ArrowLeft');", code)
        self.assertIn("skipTime(60)", code)

    def test_quality_off_keeps_the_playing_steps(self):
        code = acceptance_spec(DODGER, quality=False)
        self.assertEqual(steps(code), ["input", "round_end", "restart"])

    def test_title_is_escaped(self):
        tricky = DODGER.model_copy(update={"title": "Bob's `Game`"})
        code = acceptance_spec(tricky)
        self.assertIn("bob\\'s \\`game\\`", code)

    def test_file_name(self):
        self.assertEqual(ACCEPTANCE_FILE, "tests/acceptance.spec.ts")


if __name__ == "__main__":
    unittest.main()
