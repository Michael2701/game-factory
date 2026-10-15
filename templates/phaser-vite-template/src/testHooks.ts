import * as Phaser from 'phaser';
import { GameScene } from './scenes/GameScene';

// Test hook contract read by the tests. Generic for every game: it reads members of GameScene
// (player, score, difficulty, clickTarget) when the game has them. Games may add their own values.
export function setupTestHooks(game: Phaser.Game) {
  const gameScene = () => game.scene.getScene('GameScene') as GameScene;
  const active = () => {
    const scene = gameScene() as any;
    return scene?.sys?.isActive() ? scene : null;
  };
  (window as any).__GAME_STATE__ = {
    get scene() {
      // the most recent active scene (scenes run in the order of the game config)
      const scenes = game.scene.getScenes(true);
      return scenes[scenes.length - 1]?.scene.key ?? null;
    },
    get result() {
      return gameScene()?.result ?? null;
    },
    // the avatar the player controls (GameScene.player), if the game has one
    get player() {
      const p = active()?.player;
      return p && typeof p.x === 'number' ? { x: Math.round(p.x), y: Math.round(p.y) } : null;
    },
    // the game's main number (GameScene.score), if it has one
    get score() {
      const s = active()?.score;
      return typeof s === 'number' ? s : null;
    },
    // grows during a round if the game gets harder (GameScene.difficulty)
    get difficulty() {
      const d = active()?.difficulty;
      return typeof d === 'number' ? d : null;
    },
    // where a meaningful click goes right now (GameScene.clickTarget: {x, y} or a getter), for click games
    get clickTarget() {
      const t = active()?.clickTarget;
      return t && typeof t.x === 'number' ? { x: Math.round(t.x), y: Math.round(t.y) } : null;
    },
    // every visible text of the active scene (title, controls hint, HUD, messages): what a player can read
    get texts() {
      const scenes = game.scene.getScenes(true);
      const scene = scenes[scenes.length - 1];
      if (!scene) return [];
      return scene.children.list
        .filter((o) => o instanceof Phaser.GameObjects.Text && o.visible)
        .map((o) => (o as Phaser.GameObjects.Text).text);
    },
    // positions of every visible non-text object of the game scene except the player: the acceptance test
    // checks that something moves on its own in games where things move
    get objects() {
      const scene = active();
      if (!scene) return [];
      return scene.children.list
        .filter((o: any) => o.visible && o !== scene.player && !(o instanceof Phaser.GameObjects.Text)
          && typeof o.x === 'number')
        .map((o: any) => ({ x: Math.round(o.x), y: Math.round(o.y) }));
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
    // end the current round right away with this result (shows the result screen)
    finishRound(result: 'win' | 'lose') {
      gameScene().endGame(result);
    },
  };
}
