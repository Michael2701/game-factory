"""M21c: the per-game acceptance test works for different genres (no LLM).

Fast: the fixture games satisfy the coder's deterministic checks and their playtests are consistent.
Gated (RUN_NPM_TESTS=1): each fixture game, built from the template, passes ITS acceptance test, and
each broken variant fails at the step that checks the removed feature.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.fixtures.playtest_games import BROKEN_STEP, GAMES, game_files  # noqa: E402
from agents.generators.acceptance import ACCEPTANCE_FILE, acceptance_spec  # noqa: E402
from agents.generators.phaser_template import DEFAULT_TEMPLATE, spec_base  # noqa: E402
from agents.generators.playtest import check_playtest  # noqa: E402
from agents.nodes import test_runner  # noqa: E402
from agents.nodes.coder import gameplay_problems, phaser_problems  # noqa: E402
from agents.schemas import FileChange  # noqa: E402
from agents.tools.apply_changes import apply_changes  # noqa: E402


def project(name: str, broken: str | None = None) -> dict[str, str]:
    spec, files = game_files(name, broken)
    base = spec_base(DEFAULT_TEMPLATE, spec)
    return {**base, **files, ACCEPTANCE_FILE: acceptance_spec(spec, import_from="./fixtures")}


class FixtureGamesTest(unittest.TestCase):
    def test_specs_and_code_pass_the_deterministic_checks(self):
        for name, (spec, _, _) in GAMES.items():
            with self.subTest(name):
                self.assertEqual(check_playtest(spec), [])
                scene = game_files(name)[1]["src/scenes/GameScene.ts"]
                self.assertEqual(gameplay_problems(scene, spec), [])
                self.assertEqual(phaser_problems("GameScene", scene, scene), [])

    def test_different_genres_get_different_tests(self):
        clicker, jumper = acceptance_spec(GAMES["clicker"][0]), acceptance_spec(GAMES["jumper"][0])
        self.assertIn("clickTarget", clicker)
        self.assertNotIn("keyboard.down", clicker)
        self.assertIn("keyboard.down('Space')", jumper)
        self.assertNotIn("clickTarget", jumper)


@unittest.skipUnless(os.environ.get("RUN_NPM_TESTS") == "1", "set RUN_NPM_TESTS=1 (needs network for npm install)")
class RealFixtureGamesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "generated").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def run_game(self, name: str, broken: str | None = None):
        target = f"generated/{name}-{broken or 'ok'}"
        changes = [FileChange(path=p, operation="create", content=c, reason="fixture")
                   for p, c in project(name, broken).items()]
        self.assertTrue(apply_changes(changes, target, apply=True, root=self.root).ok)
        return test_runner.run_project_checks(target, root=self.root)

    def test_games_pass_their_own_acceptance(self):
        for name in GAMES:
            with self.subTest(name):
                result = self.run_game(name)
                self.assertEqual(result.status, "passed", (result.summary, [f.message[:300] for f in result.failures]))

    def test_removed_features_fail_at_their_step(self):
        for name, (_, _, variants) in GAMES.items():
            for broken in variants:
                with self.subTest(f"{name}/{broken}"):
                    result = self.run_game(name, broken)
                    acceptance = [f for f in result.failures if "acceptance.spec.ts" in f.name]
                    self.assertTrue(acceptance, result.summary)
                    self.assertIn(f"[{BROKEN_STEP[broken]}]", acceptance[0].message)


if __name__ == "__main__":
    unittest.main()
