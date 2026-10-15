import * as Phaser from 'phaser';
import { hint, title } from '../ui';

// Result screen: the message for the round's result, and a click anywhere starts a new round.
export class GameOverScene extends Phaser.Scene {
  constructor() {
    super('GameOverScene');
  }

  create(data: { result?: 'win' | 'lose' }) {
    title(this, data?.result === 'win' ? 'You win!' : 'Game over');
    hint(this, 'Click to play again');
    this.input.once('pointerdown', () => this.scene.start('GameScene'));
  }
}
