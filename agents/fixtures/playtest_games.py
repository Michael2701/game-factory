"""Two small hand-written games of different genres (M21c) that prove the per-game acceptance test works
for more than one kind of game, before any LLM run: a mouse clicker and a Space jumper.

Each game is its GameSpec plus the files that replace the template's GameScene. `broken` variants remove
one feature and must make the acceptance test fail at the step that checks it. Used by
tests/test_playtest_games.py (npm-gated) and scripts; never by the agents.
"""

from agents.schemas import GameSpec

CLICKER_SPEC = GameSpec.model_validate({
    "title": "Target Pop", "slug": "target-pop", "genre": "reflex",
    "core_loop": "A target circle appears somewhere; click it to score and it jumps to a new place.",
    "scenes": [{"name": "StartScene", "purpose": "Title, controls, click to start"},
               {"name": "GameScene", "purpose": "One target, score and a 30 second countdown"},
               {"name": "GameOverScene", "purpose": "Result and restart"}],
    "controls": [{"input": "Click", "action": "pop the target"}],
    "win_condition": "Score 15 points within 30 seconds.",
    "lose_condition": "The 30 second timer runs out with fewer than 15 points.",
    "test_requirements": ["window.__GAME_STATE__ exposes scene, score and result",
                          "clicking the target increases the score by 1"],
    "playtest": {"player": None, "inputs": [{"input": "Click", "expect": "score_up"}], "moves_on_its_own": False,
                 "hud": "input", "difficulty_ramps": False, "round_end": {"by": "timer", "seconds": 30}},
})

CLICKER_SCENE = """import * as Phaser from 'phaser';
import { flash, hud, PALETTE } from '../ui';

export class GameScene extends Phaser.Scene {
  result: 'win' | 'lose' | null = null;
  hudText!: Phaser.GameObjects.Text;
  score = 0;
  timeLeft = 30;
  target!: Phaser.GameObjects.Arc;

  constructor() {
    super('GameScene');
  }

  get clickTarget() {
    return this.target ? { x: this.target.x, y: this.target.y } : null;
  }

  create() {
    this.result = null;
    this.score = 0;
    this.timeLeft = 30;
    this.hudText = hud(this, '');
    this.target = this.add.circle(0, 0, 28, PALETTE.primary).setInteractive();
    this.target.on('pointerdown', () => this.hit());
    this.moveTarget();
    this.updateHud();
  }

  update(_time: number, delta: number) {
    this.tick(delta / 1000);
  }

  tick(seconds: number) {
    if (this.result !== null) return;
    this.timeLeft = Math.max(0, this.timeLeft - seconds);
    if (this.timeLeft === 0) {
      this.endGame(this.score >= 15 ? 'win' : 'lose');
      return;
    }
    this.updateHud();
  }

  hit() {
    /*SCORE*/this.score += 1;
    flash(this, PALETTE.good);
    if (this.score >= 15) {
      this.endGame('win');
      return;
    }
    this.moveTarget();
    this.updateHud();
  }

  moveTarget() {
    this.target.setPosition(Phaser.Math.Between(40, 440), Phaser.Math.Between(120, 600));
  }

  updateHud() {
    this.hudText.setText(`Score: ${this.score}   Time: ${Math.ceil(this.timeLeft)}`);
  }

  endGame(result: 'win' | 'lose') {
    if (this.result !== null) return;
    this.result = result;
    this.scene.start('GameOverScene', { result });
  }

  skipTime(seconds: number) {
    this.tick(seconds);
  }
}
"""

JUMPER_SPEC = GameSpec.model_validate({
    "title": "Hop Over", "slug": "hop-over", "genre": "runner",
    "core_loop": "Obstacles slide in from the right; press Space to jump over them; they get faster.",
    "scenes": [{"name": "StartScene", "purpose": "Title, controls, click to start"},
               {"name": "GameScene", "purpose": "Runner, ground, sliding obstacles, cleared counter"},
               {"name": "GameOverScene", "purpose": "Result and restart"}],
    "controls": [{"input": "Space", "action": "jump"}],
    "win_condition": "Clear 20 obstacles.",
    "lose_condition": "An obstacle hits the runner.",
    "test_requirements": ["window.__GAME_STATE__ exposes scene, player, difficulty and result",
                          "an obstacle touching the runner loses the game"],
    "playtest": {"player": {"moves_by_itself": False}, "inputs": [{"input": "Space", "expect": "player_up"}],
                 "moves_on_its_own": True, "hud": "time", "difficulty_ramps": True, "round_end": {"by": "hook"}},
})

JUMPER_SCENE = """import * as Phaser from 'phaser';
import { flash, hud, PALETTE } from '../ui';

export class GameScene extends Phaser.Scene {
  result: 'win' | 'lose' | null = null;
  hudText!: Phaser.GameObjects.Text;
  player!: Phaser.GameObjects.Rectangle;
  obstacles!: Phaser.Physics.Arcade.Group;
  jumpKey!: Phaser.Input.Keyboard.Key;
  elapsed = 0;
  difficulty = 1;
  cleared = 0;

  constructor() {
    super('GameScene');
  }

  create() {
    this.result = null;
    this.elapsed = 0;
    this.difficulty = 1;
    this.cleared = 0;
    this.hudText = hud(this, '');
    const ground = this.add.rectangle(240, 620, 480, 40, PALETTE.secondary);
    this.physics.add.existing(ground, true);
    this.player = this.add.rectangle(100, 580, 30, 40, PALETTE.primary);
    this.physics.add.existing(this.player);
    (this.player.body as Phaser.Physics.Arcade.Body).setGravityY(1200);
    this.physics.add.collider(this.player, ground);
    this.obstacles = this.physics.add.group();
    this.physics.add.overlap(this.player, this.obstacles, () => this.onHit(), undefined, this);
    this.jumpKey = this.input.keyboard!.addKey('SPACE');
    this.time.addEvent({ delay: 1200, loop: true, callback: () => this.spawn() });
    this.updateHud();
  }

  update(_time: number, delta: number) {
    this.advance(delta / 1000);
    const body = this.player.body as Phaser.Physics.Arcade.Body;
    /*JUMP*/if (this.jumpKey.isDown && body.blocked.down) body.setVelocityY(-600);
    this.obstacles.getChildren().forEach((o: any) => {
      if (o.x < -30) {
        o.destroy();
        this.cleared += 1;
        if (this.cleared >= 20) this.endGame('win');
      }
    });
  }

  spawn() {
    const block = this.add.rectangle(500, 585, 26, 30, PALETTE.danger);
    this.physics.add.existing(block);
    this.obstacles.add(block);
    const body = block.body as Phaser.Physics.Arcade.Body;
    body.setAllowGravity(false);
    /*SPEED*/body.setVelocityX(-200 * this.difficulty);
  }

  advance(seconds: number) {
    this.elapsed += seconds;
    this.difficulty = 1 + Math.floor(this.elapsed / 10);
    this.updateHud();
  }

  onHit() {
    flash(this, PALETTE.danger);
    this.endGame('lose');
  }

  updateHud() {
    this.hudText.setText(`Time: ${Math.floor(this.elapsed)}   Cleared: ${this.cleared}`);
  }

  endGame(result: 'win' | 'lose') {
    if (this.result !== null) return;
    this.result = result;
    this.scene.start('GameOverScene', { result });
  }

  skipTime(seconds: number) {
    this.advance(seconds);
  }
}
"""

GAMES = {
    "clicker": (CLICKER_SPEC, CLICKER_SCENE, {"no_score": ("/*SCORE*/this.score += 1;", "/*SCORE*/")}),
    "jumper": (JUMPER_SPEC, JUMPER_SCENE, {
        "no_jump": ("/*JUMP*/if (this.jumpKey.isDown && body.blocked.down) body.setVelocityY(-600);", "/*JUMP*/"),
        "frozen": ("/*SPEED*/body.setVelocityX(-200 * this.difficulty);", "/*SPEED*/"),
    }),
}
# which acceptance step each broken variant must fail at
BROKEN_STEP = {"no_score": "input", "no_jump": "input", "frozen": "world_alive"}


def game_files(name: str, broken: str | None = None) -> tuple[GameSpec, dict[str, str]]:
    """(spec, {path: content}) overriding the template for game `name`, optionally with one feature removed."""
    spec, scene, variants = GAMES[name]
    if broken:
        old, new = variants[broken]
        scene = scene.replace(old, new)
    return spec, {"src/scenes/GameScene.ts": scene}
