import * as Phaser from 'phaser';
import { GameScene } from './scenes/GameScene';

// Test hook contract read by tests/game.spec.ts. Games add their own values and methods.
export function setupTestHooks(game: Phaser.Game) {
  const gameScene = () => game.scene.getScene('GameScene') as GameScene;
  (window as any).__GAME_STATE__ = {
    get scene() {
      return game.scene.getScenes(true)[0]?.scene.key ?? null;
    },
    get result() {
      return gameScene()?.result ?? null;
    },
  };
  (window as any).__TEST_API__ = {
    startGame() {
      game.scene.getScenes(true).forEach((scene) => game.scene.stop(scene.scene.key));
      game.scene.start('GameScene');
    },
    skipTime(seconds: number) {
      gameScene().skipTime(seconds);
    },
  };
}
