import * as Phaser from 'phaser';
import { hud } from '../ui';

// Placeholder gameplay scene: the agents replace its body with the game described in the GameSpec.
export class GameScene extends Phaser.Scene {
  result: 'win' | 'lose' | null = null;
  hudText!: Phaser.GameObjects.Text;

  constructor() {
    super('GameScene');
  }

  create() {
    this.result = null;
    this.hudText = hud(this, '');
    // The game goes here. Keep the HUD current and end the round with this.endGame('win' | 'lose').
  }

  endGame(result: 'win' | 'lose') {
    if (this.result !== null) return;
    this.result = result;
    this.scene.start('GameOverScene', { result });
  }

  // Test hook: advance the game's own clock by `seconds` instantly (timers, counters, difficulty), as if
  // that much play time had passed; end the round if that is what the game does when time runs out.
  skipTime(seconds: number) {
    void seconds;
  }
}
