import * as Phaser from 'phaser';

// Placeholder gameplay scene: the agents replace its body with the game.
export class GameScene extends Phaser.Scene {
  result: 'win' | 'lose' | null = null;

  constructor() {
    super('GameScene');
  }

  create() {
    this.result = null;
    this.add.text(240, 320, 'Game goes here', { color: '#ffffff', fontSize: '28px' }).setOrigin(0.5);
  }

  // Test hook: advance the game timer by `seconds` instantly (the template has no timer yet).
  skipTime(seconds: number) {
    void seconds;
  }
}
