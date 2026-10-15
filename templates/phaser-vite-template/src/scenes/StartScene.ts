import * as Phaser from 'phaser';
import { hint, title } from '../ui';

export class StartScene extends Phaser.Scene {
  constructor() {
    super('StartScene');
  }

  create() {
    title(this, '__GAME_TITLE__');
    hint(this, '__CONTROLS_HINT__');
    hint(this, 'Click to start', 380);
    this.input.once('pointerdown', () => this.scene.start('GameScene'));
  }
}
