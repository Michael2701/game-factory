"""M21b deterministic gameplay checks, built from what qwen3 really wrote in r10-r12."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.nodes.coder import gameplay_problems, phaser_problems, unwired_lose_handlers  # noqa: E402
from agents.schemas import Control, Playtest  # noqa: E402
from agents.schemas.examples import sample_game_spec  # noqa: E402

SPEC = sample_game_spec()  # ArrowLeft / ArrowRight


def playtest_spec(controls: list[str], playtest: dict):
    base = {"player": None, "moves_on_its_own": False, "hud": "none", "difficulty_ramps": False,
            "round_end": {"by": "hook"}}
    return SPEC.model_copy(update={"controls": [Control(input=c, action="a") for c in controls],
                                   "playtest": Playtest.model_validate({**base, **playtest})})

# r12 GameScene (shortened): no keyboard input, deltaTime, a collision handler nobody registers
R12 = """export class GameScene extends Phaser.Scene {
  create() {
    this.player = this.add.rectangle(240, 580, 40, 20, PALETTE.player);
    this.physics.add.existing(this.player);
  }

  update() {
    this.elapsedTime += this.time.deltaTime / 1000;
  }

  onPlayerCollision() {
    this.endGame('lose');
    flash(this, PALETTE.hazard);
  }

  endGame(result: 'win' | 'lose') {
    this.result = result;
  }
}
"""

GOOD = """export class GameScene extends Phaser.Scene {
  create() {
    this.player = this.add.rectangle(240, 580, 40, 20, PALETTE.primary);
    this.difficulty = 1;
    this.cursors = this.input.keyboard!.createCursorKeys();
    this.physics.add.overlap(this.player, this.blocks, () => this.onPlayerCollision(), undefined, this);
    this.time.addEvent({ delay: 1000, callback: this.spawnBlock, callbackScope: this, loop: true });
  }

  update(_time: number, delta: number) {
    this.elapsed += delta / 1000;
    if (this.cursors.left.isDown) this.player.x -= 5;
  }

  private onPlayerCollision(): void {
    this.endGame('lose');
  }

  endGame(result: 'win' | 'lose') {
    this.result = result;
  }
}
"""


class FakeClockTest(unittest.TestCase):
    def test_invented_clock_apis_are_rejected(self):
        for code in ("this.elapsed += this.time.deltaTime / 1000;",   # r11, r12
                     "this.time.add(seconds);",                         # r10 fixer
                     "const d = this.time.delta;"):
            errors = phaser_problems("x", code, code)
            self.assertTrue(any("update(time: number, delta: number)" in e for e in errors), (code, errors))

    def test_real_clock_apis_pass(self):
        for code in ("this.time.addEvent({ delay: 1000, loop: true });", "this.time.delayedCall(100, f);",
                     "const now = this.time.now;", "update(_time: number, delta: number) { this.e += delta; }"):
            self.assertEqual(phaser_problems("x", code, code), [], code)


# r13 spawnBlock (shortened): velocity before group.add, and events on a body
R13_SPAWN = """import { PALETTE } from '../ui';
  create() { this.blocks = this.physics.add.group(); }
  spawnBlock() {
    const block = this.add.rectangle(x, -20, 40, 20, PALETTE.hazard);
    this.physics.add.existing(block);
    block.body.setVelocityY(200 * this.difficulty);
    this.blocks.add(block);
    block.body.on('worldbounds', (body) => { block.destroy(); });
  }
"""
GOOD_SPAWN = """import { PALETTE } from '../ui';
  create() { this.blocks = this.physics.add.group(); }
  spawnBlock() {
    const block = this.add.rectangle(x, -20, 40, 20, PALETTE.hazard);
    this.physics.add.existing(block);
    this.blocks.add(block);
    (block.body as Phaser.Physics.Arcade.Body).setVelocityY(200);
  }
  update() { this.blocks.getChildren().forEach((b: any) => { if (b.y > 700) b.destroy(); }); }
"""


class SpawnTest(unittest.TestCase):
    def test_r13_spawn_is_rejected(self):
        errors = phaser_problems("x", R13_SPAWN, R13_SPAWN)
        self.assertTrue(any("physics body has no events" in e for e in errors), errors)
        self.assertTrue(any("['block'] get a velocity BEFORE being added to a physics group" in e for e in errors),
                        errors)

    def test_correct_spawn_passes(self):
        self.assertEqual(phaser_problems("x", GOOD_SPAWN, GOOD_SPAWN), [])

    def test_velocity_order_only_matters_for_physics_groups(self):
        plain = R13_SPAWN.replace("this.physics.add.group()", "this.add.group()").replace(
            "    block.body.on('worldbounds', (body) => { block.destroy(); });\n", "")
        self.assertEqual(phaser_problems("x", plain, plain), [])
        world = "this.physics.world.on('worldbounds', (body) => body.gameObject.destroy());"
        self.assertEqual(phaser_problems("x", world, world), [])  # world events exist


class UiImportTest(unittest.TestCase):
    def test_helpers_need_an_import(self):
        code = "export class GameScene {\n  create() {\n    this.add.circle(1, 2, 3, PALETTE.primary);\n    flash(this);\n  }\n}\n"
        errors = phaser_problems("x", code, code)
        self.assertTrue(any("uses ['PALETTE', 'flash'] from src/ui.ts without importing them" in e for e in errors),
                        errors)
        ok = "import { flash, PALETTE } from '../ui';\n" + code
        self.assertEqual(phaser_problems("x", ok, ok), [])
        self.assertEqual(phaser_problems("x", "this.title = 'x'; this.hud(1);", ""), [])  # members, not helpers


class GameplayTest(unittest.TestCase):
    def test_r12_scene_fails_both_must_haves(self):
        errors = gameplay_problems(R12, SPEC)
        self.assertTrue(any("reads no keyboard input" in e for e in errors), errors)
        self.assertTrue(any("onPlayerCollision() ends the game with 'lose' but is never called" in e for e in errors),
                        errors)

    def test_complete_scene_passes(self):
        self.assertEqual(gameplay_problems(GOOD, SPEC), [])

    def test_keyboard_variants(self):
        space = playtest_spec(["Space"], {"player": None, "inputs": [{"input": "Space", "expect": "state_changes"}]})
        for line in ("this.input.keyboard!.on('keydown-SPACE', f);", "this.input.keyboard?.addKey('SPACE');",
                     "this.keys = this.input.keyboard.addKeys('W,A,S,D');"):
            self.assertEqual(gameplay_problems(f"  create() {{ {line} }}\n", space), [], line)
        errors = gameplay_problems("  create() {}\n", space)
        self.assertTrue(any("presses the real keys ['Space']" in e for e in errors), errors)  # not only arrows

    def test_mouse_game_needs_no_keyboard_but_a_click_target(self):
        clicker = playtest_spec(["Click"], {"player": None, "inputs": [{"input": "Click", "expect": "score_up"}],
                                            "hud": "input"})
        errors = gameplay_problems("  create() {}\n", clicker)
        self.assertFalse(any("keyboard" in e for e in errors), errors)
        self.assertTrue(any("`clickTarget`" in e for e in errors), errors)
        self.assertTrue(any("`score`" in e for e in errors), errors)
        ok = ("  score = 0;\n  create() {}\n  get clickTarget() { return this.target ? { x: this.target.x, "
              "y: this.target.y } : null; }\n")
        self.assertEqual(gameplay_problems(ok, clicker), [])

    def test_lose_handlers(self):
        self.assertEqual(unwired_lose_handlers(R12), ["onPlayerCollision"])
        self.assertEqual(unwired_lose_handlers(GOOD), [])
        # endGame('lose') inside update() / an inline overlap callback in create(): Phaser calls those itself
        inline = "  create() {\n    this.physics.add.overlap(a, b, () => this.endGame('lose'));\n  }\n"
        self.assertEqual(unwired_lose_handlers(inline), [])


if __name__ == "__main__":
    unittest.main()
