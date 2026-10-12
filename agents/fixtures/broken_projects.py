"""Synthetic broken game projects + failing TestResults for the fixer (M15).

Each case is a tiny Phaser + Vite project in memory with one bug (two-bugs: two), the TestResult
the test runner would produce for it, and a deterministic `is_fixed` check used to judge
whether a proposed fix is plausible (the culprit file changed in the right way).
BASE_FILES itself is a complete, passing project (build + 3 Playwright tests, M16):
the fix loop writes a case to disk and proves the fix by really rebuilding and testing.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from agents.schemas import CommandResult, TestFailure, TestResult

PACKAGE_JSON = json.dumps({
    "name": "dodge-demo",
    "private": True,
    "type": "module",
    "scripts": {"dev": "vite", "build": "vite build"},
    "dependencies": {"phaser": "3.90.0"},
    "devDependencies": {"vite": "8.3.1", "typescript": "6.0.3", "@playwright/test": "1.62.0"},
}, indent=2) + "\n"

INDEX_HTML = """<!doctype html>
<html>
  <head><meta charset="utf-8" /><title>Dodge Demo</title></head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
"""

MAIN_TS = """import * as Phaser from 'phaser';
import { StartScene } from './scenes/StartScene';
import { GameScene } from './scenes/GameScene';
import { setupTestHooks } from './testHooks';

const game = new Phaser.Game({
  type: Phaser.AUTO,
  width: 480,
  height: 640,
  parent: 'app',
  scene: [StartScene, GameScene],
});

setupTestHooks(game);
"""

START_SCENE = """import * as Phaser from 'phaser';

export class StartScene extends Phaser.Scene {
  constructor() {
    super('StartScene');
  }

  create() {
    this.add.text(240, 320, 'Click to start', { color: '#ffffff' }).setOrigin(0.5);
    this.input.once('pointerdown', () => this.scene.start('GameScene'));
  }
}
"""

GAME_SCENE = """import * as Phaser from 'phaser';

export class GameScene extends Phaser.Scene {
  timeLeft = 60;
  result: 'win' | 'lose' | null = null;

  constructor() {
    super('GameScene');
  }

  create() {
    this.timeLeft = 60;
    this.result = null;
  }

  skipTime(seconds: number) {
    this.timeLeft = Math.max(0, this.timeLeft - seconds);
    if (this.timeLeft === 0) {
      this.result = 'win';
    }
  }
}
"""

TEST_HOOKS = """import * as Phaser from 'phaser';
import { GameScene } from './scenes/GameScene';

export function setupTestHooks(game: Phaser.Game) {
  const scene = () => game.scene.getScene('GameScene') as GameScene;
  (window as any).__GAME_STATE__ = {
    get scene() {
      return game.scene.getScenes(true)[0]?.scene.key ?? null;
    },
    get result() {
      return scene()?.result ?? null;
    },
  };
  (window as any).__TEST_API__ = {
    startGame() {
      game.scene.stop('StartScene');
      game.scene.start('GameScene');
    },
    skipTime(seconds: number) {
      scene().skipTime(seconds);
    },
  };
}
"""

TESTS = """import { test, expect } from '@playwright/test';

test('game loads into the start scene', async ({ page }) => {
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__GAME_STATE__?.scene === 'StartScene');
});

test('surviving 60 seconds wins', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => (window as any).__TEST_API__.startGame());
  await page.evaluate(() => (window as any).__TEST_API__.skipTime(60));
  await page.waitForFunction(() => (window as any).__GAME_STATE__.result === 'win');
});

test('the game scene starts', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => (window as any).__TEST_API__.startGame());
  await page.waitForFunction(() => (window as any).__GAME_STATE__.scene === 'GameScene');
  expect(await page.evaluate(() => (window as any).__GAME_STATE__.result)).toBeNull();
});
"""

PREVIEW_PORT = 41730  # fixed port for `vite preview` (Playwright webServer); one fixture run at a time

PLAYWRIGHT_CONFIG = f"""import {{ defineConfig }} from '@playwright/test';

export default defineConfig({{
  testDir: 'tests',
  retries: 0,
  timeout: 15000,
  use: {{ baseURL: 'http://127.0.0.1:{PREVIEW_PORT}', browserName: 'chromium', headless: true }},
  webServer: {{
    command: 'npx vite preview --port {PREVIEW_PORT} --strictPort --host 127.0.0.1',
    url: 'http://127.0.0.1:{PREVIEW_PORT}',
    timeout: 60000,
  }},
}});
"""

BASE_FILES = {
    "package.json": PACKAGE_JSON,
    "playwright.config.ts": PLAYWRIGHT_CONFIG,
    "index.html": INDEX_HTML,
    "src/main.ts": MAIN_TS,
    "src/scenes/StartScene.ts": START_SCENE,
    "src/scenes/GameScene.ts": GAME_SCENE,
    "src/testHooks.ts": TEST_HOOKS,
    "tests/game.spec.ts": TESTS,
}

PROJECT_DIR = "generated/dodge-demo"


@dataclass
class BrokenCase:
    name: str
    description: str
    files: dict[str, str]
    test_result: TestResult
    culprit: str  # the file a plausible fix must change
    is_fixed: Callable[[str], bool]  # new culprit content -> bug gone?
    also_broken: tuple[str, ...] = ()  # further broken files the first error does not name yet (fix loop)
    fails_for_real: bool = True  # False: the bug does not break the pinned stack on macOS (see the case doc)
    notes: list[str] = field(default_factory=list)


def _build_failure(message: str) -> TestResult:
    install = CommandResult(command="npm install --ignore-scripts --no-audit --no-fund", cwd=PROJECT_DIR,
                            exit_code=0, stdout="added 25 packages in 4s\n", duration_s=4.0)
    build = CommandResult(command="npm run build", cwd=PROJECT_DIR, exit_code=1,
                          stdout="> dodge-demo@0.0.0 build\n> vite build\n", stderr=message, duration_s=2.1)
    return TestResult(status="failed", command_results=[install, build],
                      failures=[TestFailure(name="npm run build", message=message)],
                      summary="install ok · build failed (exit 1)")


IMPORT_CASE_MESSAGE = """vite v8.3.1 building for production...
transforming...
✓ 6 modules transformed.
error during build:
Could not resolve './scenes/gameScene' from src/main.ts
file: /project/generated/dodge-demo/src/main.ts
"""

PHASER_DEFAULT_MESSAGE = """'default' is not exported by node_modules/phaser/dist/phaser.esm.js, imported by src/scenes/StartScene.ts
file: /project/generated/dodge-demo/src/scenes/StartScene.ts:1:7
1: import Phaser from 'phaser';
          ^
2:
3: export class StartScene extends Phaser.Scene {
error during build:
Error: 'default' is not exported by node_modules/phaser/dist/phaser.esm.js, imported by src/scenes/StartScene.ts
"""


def import_case() -> BrokenCase:
    """main.ts imports './scenes/gameScene' (wrong casing) -> build cannot resolve it on Linux.

    Not a real failure on a case-insensitive filesystem (macOS default): vite resolves the
    path and the project passes (verified in M16). Kept for the fixer dry run (M15).
    """
    files = dict(BASE_FILES)
    files["src/main.ts"] = MAIN_TS.replace("'./scenes/GameScene'", "'./scenes/gameScene'")
    return BrokenCase(
        name="import-case",
        description="wrong casing in an import path (./scenes/gameScene vs GameScene.ts)",
        files=files,
        test_result=_build_failure(IMPORT_CASE_MESSAGE),
        culprit="src/main.ts",
        is_fixed=lambda text: "'./scenes/GameScene'" in text and "gameScene'" not in text,
        fails_for_real=False,
    )


def phaser_default_case() -> BrokenCase:
    """StartScene.ts uses `import Phaser from 'phaser'`: Phaser 3.90 ESM has no default export.

    Real failure seen in M14 (generated/block-dodger, vite ^2.8). With the pinned vite 8.3.1
    the default import is interop-resolved and the project passes (verified in M16). Kept for
    the fixer dry run (M15).
    """
    files = dict(BASE_FILES)
    files["src/scenes/StartScene.ts"] = START_SCENE.replace("import * as Phaser from 'phaser';",
                                                            "import Phaser from 'phaser';")
    return BrokenCase(
        name="phaser-default",
        description="default import of Phaser, which phaser.esm.js does not export",
        files=files,
        test_result=_build_failure(PHASER_DEFAULT_MESSAGE),
        culprit="src/scenes/StartScene.ts",
        is_fixed=lambda text: not re.search(r"import\s+Phaser\s+from\s+['\"]phaser['\"]", text)
        and bool(re.search(r"import\s+(\*\s+as\s+Phaser|\{[^}]*\bScene\b[^}]*\})\s+from\s+['\"]phaser['\"]", text)),
        fails_for_real=False,
    )


MISSING_FILE_MESSAGE = """✗ Build failed in 25ms
error during build:
Build failed with 1 error:

[UNRESOLVED_IMPORT] Could not resolve './scenes/PlayScene' in src/main.ts
   ╭─[ src/main.ts:3:27 ]
   │
 3 │ import { GameScene } from "./scenes/PlayScene";
   │                           ──────────┬─────────
   │                                     ╰─────────── Module not found.
   │
   │ Help: 'src/main.ts' is imported by the following path:
   │         - src/main.ts
   │         - index.html
───╯
"""  # real vite 8.3.1 output (M16)

WIN_LOGIC_MESSAGE = """Test timeout of 15000ms exceeded.
Error: page.waitForFunction: Test timeout of 15000ms exceeded.

  10 |   await page.evaluate(() => (window as any).__TEST_API__.startGame());
  11 |   await page.evaluate(() => (window as any).__TEST_API__.skipTime(60));
> 12 |   await page.waitForFunction(() => (window as any).__GAME_STATE__.result === 'win');
     |              ^
  13 | });
    at /project/generated/dodge-demo/tests/game.spec.ts:12:14
"""  # real Playwright 1.62.0 output (M16)


def missing_file_case() -> BrokenCase:
    """main.ts imports './scenes/PlayScene', which does not exist (the class is in GameScene.ts)."""
    files = dict(BASE_FILES)
    files["src/main.ts"] = MAIN_TS.replace("'./scenes/GameScene'", "'./scenes/PlayScene'")
    return BrokenCase(
        name="missing-file",
        description="import of a scene file that does not exist (./scenes/PlayScene; the class is in GameScene.ts)",
        files=files,
        test_result=_build_failure(MISSING_FILE_MESSAGE),
        culprit="src/main.ts",
        is_fixed=lambda text: "'./scenes/GameScene'" in text and "PlayScene'" not in text,
    )


def win_logic_case() -> BrokenCase:
    """GameScene.skipTime checks `timeLeft < 0`, which never happens: the win test fails at runtime."""
    files = dict(BASE_FILES)
    files["src/scenes/GameScene.ts"] = GAME_SCENE.replace("this.timeLeft === 0", "this.timeLeft < 0")
    install = CommandResult(command="npm install", cwd=PROJECT_DIR, exit_code=0, stdout="up to date\n", duration_s=1.0)
    build = CommandResult(command="npm run build", cwd=PROJECT_DIR, exit_code=0, stdout="✓ built\n", duration_s=1.5)
    tests = CommandResult(command="npx playwright test --reporter=json", cwd=PROJECT_DIR, exit_code=1,
                          stdout="{}", duration_s=17.0)
    return BrokenCase(
        name="win-logic",
        description="win check `timeLeft < 0` can never be true: the Playwright win test fails (runtime bug)",
        files=files,
        test_result=TestResult(
            status="failed", command_results=[install, build, tests],
            failures=[TestFailure(name="game.spec.ts › surviving 60 seconds wins", message=WIN_LOGIC_MESSAGE)],
            summary="install ok · build ok · tests 2/3 passed"),
        culprit="src/scenes/GameScene.ts",
        is_fixed=lambda text: bool(re.search(r"timeLeft\s*(<=\s*0|===?\s*0)", text)),
    )


def two_bugs_case() -> BrokenCase:
    """missing-file + win-logic. The build error hides the runtime bug: the fix loop needs two rounds.

    `test_result` is the first failure (the unresolved import in main.ts).
    """
    first, second = missing_file_case(), win_logic_case()
    files = dict(first.files)
    files[second.culprit] = second.files[second.culprit]
    return BrokenCase(
        name="two-bugs",
        description="missing-file + win-logic together (build error first, then a failing test)",
        files=files,
        test_result=first.test_result,
        culprit=first.culprit,
        is_fixed=first.is_fixed,
        also_broken=(second.culprit,),
    )


CASES: dict[str, Callable[[], BrokenCase]] = {
    "import-case": import_case,
    "missing-file": missing_file_case,
    "phaser-default": phaser_default_case,
    "two-bugs": two_bugs_case,
    "win-logic": win_logic_case,
}
