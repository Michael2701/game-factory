import * as Phaser from 'phaser';
import { GameScene } from './scenes/GameScene';

// Test hook contract read by tests/game.spec.ts. Games add their own values and methods.
export function setupTestHooks(game: Phaser.Game) {
  const gameScene = () => game.scene.getScene('GameScene') as GameScene;
  (window as any).__GAME_STATE__ = {
    get scene() {
      // the most recent active scene (scenes run in the order of the game config)
      const active = game.scene.getScenes(true);
      return active[active.length - 1]?.scene.key ?? null;
    },
    get result() {
      return gameScene()?.result ?? null;
    },
    // the player's x position (the template has no player yet; the acceptance test moves it with arrow keys)
    get playerX() {
      return (gameScene() as any)?.player?.x ?? null;
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
