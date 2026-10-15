import * as Phaser from 'phaser';
import { StartScene } from './scenes/StartScene';
import { GameScene } from './scenes/GameScene';
import { GameOverScene } from './scenes/GameOverScene';
import { setupTestHooks } from './testHooks';

const game = new Phaser.Game({
  type: Phaser.AUTO,
  width: 480,
  height: 640,
  parent: 'app',
  backgroundColor: '#1d1d2b',
  physics: { default: 'arcade', arcade: { debug: false } },
  scene: [StartScene, GameScene, GameOverScene],
});

setupTestHooks(game);
