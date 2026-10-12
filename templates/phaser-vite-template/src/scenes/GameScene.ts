import * as Phaser from 'phaser';

// Placeholder gameplay scene: the agents replace its body with the game.
export class GameScene extends Phaser.Scene {
  result: 'win' | 'lose' | null = null;

  constructor() {
    super('GameScene');
  }

  create() {
    this.result = null;
    // The game goes here (players, timers, collisions); end it with this.endGame('win' | 'lose').
  }

  endGame(result: 'win' | 'lose') {
    this.result = result;
    this.scene.start('GameOverScene', { result });
  }

  // Test hook: advance the game timer by `seconds` instantly: reduce the remaining time and call
  // endGame('win') when it reaches 0 (the template has no timer yet).
  skipTime(seconds: number) {
    void seconds;
  }
}
