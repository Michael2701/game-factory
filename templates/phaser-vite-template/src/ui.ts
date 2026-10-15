import * as Phaser from 'phaser';

// Shared look for every scene (M22): palette, readable text, HUD and event feedback. No image assets needed.
// Roles, not genres: primary = what the player controls/clicks, danger = what hurts, good = what helps.
export const PALETTE = {
  background: 0x1d1d2b,
  primary: 0x4fc3f7,
  secondary: 0xb388ff,
  danger: 0xff5252,
  good: 0x69f0ae,
  accent: 0xffd54f,
  text: '#ffffff',
  muted: '#b0bec5',
};

export function title(scene: Phaser.Scene, text: string, y = 220): Phaser.GameObjects.Text {
  return scene.add.text(240, y, text, { color: PALETTE.text, fontSize: '40px', fontStyle: 'bold' }).setOrigin(0.5);
}

export function hint(scene: Phaser.Scene, text: string, y = 300): Phaser.GameObjects.Text {
  return scene.add.text(240, y, text, { color: PALETTE.muted, fontSize: '20px', align: 'center' }).setOrigin(0.5);
}

// Top-left HUD (time, score, level): update it with hudText.setText(...) every time a value changes.
export function hud(scene: Phaser.Scene, text = ''): Phaser.GameObjects.Text {
  return scene.add.text(16, 16, text, { color: PALETTE.text, fontSize: '22px' }).setDepth(10);
}

// Feedback for events: hits, pickups, win/lose.
export function flash(scene: Phaser.Scene, color = 0xffffff): void {
  const c = Phaser.Display.Color.IntegerToColor(color);
  scene.cameras.main.flash(150, c.red, c.green, c.blue);
}

export function shake(scene: Phaser.Scene): void {
  scene.cameras.main.shake(200, 0.01);
}
