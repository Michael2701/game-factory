"""M21 acceptance spec generator: real input only, hooks only for state and time control."""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.generators.acceptance import ACCEPTANCE_FILE, acceptance_spec, arrow_keys  # noqa: E402
from agents.schemas import Control  # noqa: E402
from agents.schemas.examples import sample_game_spec  # noqa: E402

SPEC = sample_game_spec()  # Block Dodger: ArrowLeft / ArrowRight


class AcceptanceSpecTest(unittest.TestCase):
    def setUp(self):
        self.code = acceptance_spec(SPEC)

    def test_arrow_keys_from_spec(self):
        self.assertEqual(arrow_keys(SPEC), [("ArrowLeft", "<"), ("ArrowRight", ">")])
        jump = SPEC.model_copy(update={"controls": [Control(input="Space", action="jump")]})
        self.assertEqual(arrow_keys(jump), [])
        self.assertNotIn("keyboard.down", acceptance_spec(jump))

    def test_real_input_only(self):
        for key in ("ArrowLeft", "ArrowRight"):
            self.assertIn(f"await page.keyboard.down('{key}');", self.code)
            self.assertIn(f"await page.keyboard.up('{key}');", self.code)
        self.assertIn("await page.locator('canvas').click({ position: { x: 240, y: 320 } });", self.code)
        api_calls = re.findall(r"__TEST_API__\.(\w+)\(", self.code)
        self.assertEqual(api_calls, ["skipTime"])  # never startGame / movePlayer*

    def test_movement_checks_direction_and_stillness(self):
        self.assertIn("__GAME_STATE__.playerX < start", self.code)
        self.assertIn("__GAME_STATE__.playerX > start", self.code)
        self.assertIn("'the player moved with no key held'", self.code)
        self.assertIn("ArrowLeft did not move the player", self.code)

    def test_screenshots_and_game_over(self):
        for shot in ("menu", "gameplay", "gameover"):
            self.assertIn(f"path: 'test-results/acceptance/{shot}.png'", self.code)
        self.assertIn("scene === 'GameOverScene'", self.code)

    def test_parameters(self):
        self.assertEqual(ACCEPTANCE_FILE, "tests/acceptance.spec.ts")
        code = acceptance_spec(SPEC, player_x="__GAME_STATE__.player.x", import_from="./fixtures")
        self.assertTrue(code.startswith("import { test, expect } from './fixtures';"))
        self.assertIn("(window as any).__GAME_STATE__.player.x", code)
        self.assertNotIn("playerX", code)


if __name__ == "__main__":
    unittest.main()
