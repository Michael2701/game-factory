import { test, expect } from '@playwright/test';

// Smoke tests of the template's hook contract; the test writer replaces them with game tests.
test('game loads into the start scene', async ({ page }) => {
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__GAME_STATE__?.scene === 'StartScene');
});

test('startGame switches to the game scene', async ({ page }) => {
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__GAME_STATE__?.scene === 'StartScene');
  await page.evaluate(() => (window as any).__TEST_API__.startGame());
  await page.waitForFunction(() => (window as any).__GAME_STATE__.scene === 'GameScene');
});

test('a new game has no result yet', async ({ page }) => {
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__GAME_STATE__?.scene === 'StartScene');
  await page.evaluate(() => (window as any).__TEST_API__.startGame());
  await page.waitForFunction(() => (window as any).__GAME_STATE__.scene === 'GameScene');
  await page.evaluate(() => (window as any).__TEST_API__.skipTime(1));
  expect(await page.evaluate(() => (window as any).__GAME_STATE__.result)).toBeNull();
});
