"""M20 Phaser 3 pitfalls found in real generated games, checked deterministically.

Coder and fixer reject Phaser 2 key events (the player could not move in every M19/M20 run)
and sprites with textures that are never loaded; the fixer sees its earlier attempts.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agents.generators.phaser_template import instantiate  # noqa: E402
from agents.nodes.coder import check_changes, phaser_problems  # noqa: E402
from agents.nodes.fixer import attempt_history, check_fix, fix  # noqa: E402
from agents.prompts import load_prompt  # noqa: E402
from agents.schemas import FileChange, FileChangeSet, GameFactoryState, LoopStep, TestResult  # noqa: E402
from agents.schemas.examples import sample_game_spec, sample_template_task_plan  # noqa: E402
from fakes import FakeLLM  # noqa: E402

GOOD_SCENE = """import * as Phaser from 'phaser';
export class GameScene extends Phaser.Scene {
  create() {
    this.cursors = this.input.keyboard!.createCursorKeys();
    this.player = this.add.rectangle(240, 600, 30, 30, 0x00ff00);
    this.physics.add.existing(this.player);
    this.input.keyboard!.on('keydown-SPACE', () => {});
  }
}
"""


def problems(content: str, project: str = "") -> list[str]:
    return phaser_problems("x.ts", content, project or content)


class PhaserProblemsTest(unittest.TestCase):
    def test_good_code_passes(self):
        self.assertEqual(problems(GOOD_SCENE), [])

    def test_phaser2_key_events(self):
        for line in ["this.input.on('keydown_LEFT', () => {});", 'this.input.keyboard.on("keyup_RIGHT", f);',
                     "this.input.on('keydown', f);"]:
            with self.subTest(line=line):
                errors = problems(line)
                self.assertTrue(any("Phaser 2 key events" in e for e in errors), errors)

    def test_textures_must_be_loaded_or_generated(self):
        use = "this.player = this.physics.add.sprite(240, 600, 'player');"
        self.assertTrue(any("['player']" in e for e in problems(use)))
        self.assertEqual(problems(use, use + "\nthis.load.image('player', 'p.png');"), [])
        self.assertEqual(problems(use, use + "\ng.generateTexture('player', 30, 30);"), [])

    def test_coder_rejects(self):
        task = sample_template_task_plan().tasks[0]
        base = instantiate("block-dodger", "Block Dodger")
        changes = FileChangeSet(changes=[
            FileChange(path="src/scenes/StartScene.ts", operation="update", content="x\n", reason="r"),
            FileChange(path="src/scenes/GameScene.ts", operation="update",
                       content="this.input.on('keydown_LEFT', f);\n", reason="r"),
            FileChange(path="src/scenes/GameOverScene.ts", operation="create", content="x\n", reason="r")])
        errors = check_changes(changes, task, base)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("Phaser 2 key events", errors[0])

    def test_fixer_rejects_only_what_it_adds(self):
        old = "this.input.on('keydown_LEFT', f);\nconst a = 1;\n"  # existing bug: not the fixer's fault
        relevant = {"src/scenes/GameScene.ts": old}
        keeps = FileChangeSet(changes=[FileChange(path="src/scenes/GameScene.ts", operation="update",
                                                  content=old.replace("1", "2"), reason="r")])
        self.assertEqual(check_fix(keeps, relevant, []), [])
        adds = FileChangeSet(changes=[FileChange(path="src/scenes/GameScene.ts", operation="update",
                                                 content=old + "this.input.on('keyup_LEFT', g);\n", reason="r")])
        self.assertTrue(any("Phaser 2 key events" in e for e in check_fix(adds, relevant, [])))

    def test_prompts_carry_the_notes(self):
        self.assertIn("createCursorKeys()", load_prompt("coder"))
        self.assertIn("shape.body as Phaser.Physics.Arcade.Body", load_prompt("fixer"))
        # M20 r5: a "test the keyboard" rule made the model use waitForTimeout (forbidden) -> removed
        self.assertNotIn("page.keyboard.down", load_prompt("test_writer"))


class BootAndTemplateTest(unittest.TestCase):
    """M20 r3: tests called __TEST_API__ before the game booted; the template's scene getter took the first scene."""

    def test_api_call_before_boot_rejected(self):
        from agents.nodes.test_writer import check_tests
        early = ("import { test, expect } from '@playwright/test';\n"
                 "test('a', async ({ page }) => { await page.goto('/');\n"
                 "  await page.waitForFunction(() => (window as any).__GAME_STATE__?.scene === 'StartScene'); });\n"
                 "test('b', async ({ page }) => { await page.goto('/');\n"
                 "  await page.evaluate(() => (window as any).__TEST_API__.startGame());\n"
                 "  await page.waitForFunction(() => (window as any).__GAME_STATE__.scene === 'GameScene'); });\n"
                 "test('c', async ({ page }) => { await page.goto('/');\n"
                 "  await page.waitForFunction(() => (window as any).__GAME_STATE__?.scene === 'StartScene');\n"
                 "  await page.evaluate(() => (window as any).__TEST_API__.startGame()); });\n")
        changes = FileChangeSet(changes=[FileChange(path="tests/game.spec.ts", operation="create", content=early,
                                                    reason="r")])
        errors = [e for e in check_tests(changes, sample_game_spec(), {}) if "before the game has booted" in e]
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("test 'b'", errors[0])

    def test_template_scene_getter_and_game_scene(self):
        files = instantiate("x", "X")
        self.assertIn("active[active.length - 1]?.scene.key", files["src/testHooks.ts"])
        self.assertNotIn("this.add.text", files["src/scenes/GameScene.ts"])  # no visible placeholder
        self.assertIn("endGame(result: 'win' | 'lose')", files["src/scenes/GameScene.ts"])


class NormalizeTestsTest(unittest.TestCase):
    """M20 r4: one racy scene read in 11 tests failed the whole run; such races are now rewritten."""

    def test_scene_expect_rewritten(self):
        from agents.nodes.test_writer import normalize_test_code
        code = ("test('w', async ({ page }) => {\n  await page.goto('/');\n"
                "  await page.waitForFunction(() => (window as any).__GAME_STATE__?.scene === 'StartScene');\n"
                "  expect(await page.evaluate(() => (window as any).__GAME_STATE__.scene)).toBe('GameOverScene');\n"
                "  expect(await page.evaluate(() => window.__GAME_STATE__?.scene)).toEqual(\"GameScene\");\n});\n")
        out, notes = normalize_test_code(code)
        self.assertNotIn("expect(await page.evaluate", out)
        self.assertIn("__GAME_STATE__?.scene === 'GameOverScene')", out)
        self.assertIn("__GAME_STATE__?.scene === 'GameScene')", out)
        self.assertEqual(notes, ["2 scene check(s) now wait for the scene"])

    def test_boot_wait_inserted_only_where_needed(self):
        from agents.nodes.test_writer import BOOT_WAIT, normalize_test_code
        code = ("test('a', async ({ page }) => {\n  await page.goto('/');\n"
                "  await page.evaluate(() => (window as any).__TEST_API__.startGame());\n});\n"
                "test('b', async ({ page }) => {\n  await page.goto('/');\n  " + BOOT_WAIT + "\n"
                "  await page.evaluate(() => (window as any).__TEST_API__.startGame());\n});\n")
        out, notes = normalize_test_code(code)
        self.assertEqual(out.count(BOOT_WAIT), 2)
        self.assertIn("  await page.goto('/');\n  " + BOOT_WAIT + "\n  await page.evaluate", out.split("test('b'")[0])
        self.assertEqual(notes, ["1 test(s) now wait for the game to boot before __TEST_API__"])
        self.assertEqual(normalize_test_code(out), (out, []))  # idempotent

    def test_write_tests_normalizes_before_checking(self):
        from agents.nodes.test_writer import write_tests
        tests = ("import { test, expect } from '@playwright/test';\n" + "".join(
            f"test('t{i}', async ({{ page }}) => {{\n  await page.goto('/');\n"
            f"  await page.evaluate(() => (window as any).__TEST_API__.startGame());\n"
            f"  expect(await page.evaluate(() => (window as any).__GAME_STATE__.scene)).toBe('GameScene');\n}});\n"
            for i in range(3)))
        reply = json.dumps({"changes": [{"path": "tests/game.spec.ts", "operation": "create", "content": tests,
                                         "reason": "tests"}]})
        llm = FakeLLM(reply)
        result = write_tests(sample_game_spec(), {}, llm=llm)
        self.assertIsInstance(result, FileChangeSet, result)
        self.assertEqual(len(llm.prompts), 1)  # no repair needed
        self.assertIn("(normalized: 3 scene check(s) now wait for the scene; 3 test(s) now wait for the game",
                      result.changes[0].reason)


class AttemptHistoryTest(unittest.TestCase):
    def test_history_lines_and_prompt(self):
        state = GameFactoryState(user_idea="x", loop_history=[
            LoopStep(step="test", attempt=0, status="failed", summary="tests 9/10 passed"),
            LoopStep(step="fix", attempt=1, status="proposed", summary="use setVelocity", files=["src/testHooks.ts"]),
            LoopStep(step="apply_fix", attempt=1, status="applied", files=["src/testHooks.ts"]),
            LoopStep(step="test", attempt=1, status="failed", summary="tests 9/10 passed")])
        history = attempt_history(state)
        self.assertEqual(history, ["#1 fix proposed: use setVelocity [src/testHooks.ts]",
                                   "#1 apply_fix applied:  [src/testHooks.ts]",
                                   "#1 test failed: tests 9/10 passed"])
        llm = FakeLLM('{"changes": []}')
        failed = TestResult(status="failed", summary="tests 9/10 passed",
                            failures=[{"name": "game.spec.ts › spawn", "message": "TypeError"}])
        fix(failed, {"src/testHooks.ts": "x\n"}, sample_game_spec(), llm=llm, previous_attempts=history)
        self.assertIn("#1 fix proposed: use setVelocity [src/testHooks.ts]", llm.prompts[0])
        llm = FakeLLM('{"changes": []}')
        fix(failed, {"src/testHooks.ts": "x\n"}, sample_game_spec(), llm=llm)
        self.assertIn("(none: this is the first attempt)", llm.prompts[0])


if __name__ == "__main__":
    unittest.main()
