"""Deterministic acceptance test for a generated game (M21; per game since M21c): proves a human can play it.

Written by code from the game's playtest plan (GameSpec.playtest, agents/generators/playtest.py), never
by the LLM, and locked for the agents. It uses REAL input only: pointer clicks on the canvas (start,
restart, click targets the game reports) and real key presses. Test hooks are used only to read state
and for deterministic time control (`skipTime`, `finishRound`). Screenshots go to test-results/acceptance/.

Steps run in ACCEPTANCE_STEPS order and stop at the first failure; each failure message starts with
`[step]`. Only the steps this game's playtest asks for are generated.
"""

import json

from agents.generators.playtest import CLICK, playtest_of
from agents.schemas import GameSpec, Playtest

ACCEPTANCE_FILE = "tests/acceptance.spec.ts"
SHOTS_DIR = "test-results/acceptance"
STILL_MS = 300  # no input for this long -> a self-standing avatar must not move (catches fake/animated hooks)
MOVE_TIMEOUT_MS = 3000
ALIVE_TIMEOUT_MS = 4000  # M21b: real play time for spawn timers to fire (r13: the first block came after 1 s)
# Generic step tags in run order (the reviewer and the fix-loop ranking rely on this order).
ACCEPTANCE_STEPS = ("start_screen_explains_controls", "input", "world_alive", "hud_visible", "difficulty_ramps",
                    "round_end", "feedback_on_events", "restart")
QUALITY_CHECKS = ACCEPTANCE_STEPS  # kept name (M22)
CONTROL_WORDS = r"←|→|↑|↓|arrow|left|right|up|down|space|key|click|tap|mouse|press|drag|jump|move"

STATE = "(window as any).__GAME_STATE__"
TEXTS = f"(({STATE}?.texts ?? []) as string[]).join(' | ')"
EXPECT = {  # (condition on `now` vs `before` state, what it means)
    "player_left": ("now.player && before.player && now.player.x < before.player.x", "move the avatar left"),
    "player_right": ("now.player && before.player && now.player.x > before.player.x", "move the avatar right"),
    "player_up": ("now.player && before.player && now.player.y < before.player.y", "move the avatar up"),
    "player_down": ("now.player && before.player && now.player.y > before.player.y", "move the avatar down"),
    "score_up": ("typeof now.score === 'number' && now.score > before.score", "increase __GAME_STATE__.score"),
    "state_changes": ("JSON.stringify(now) !== JSON.stringify(before)", "change the game state"),
}
SNAPSHOT = (f"(() => {{ const s = {STATE} ?? {{}}; return {{ player: s.player ?? null, score: s.score ?? null, "
            "objects: s.objects ?? [], texts: s.texts ?? [], result: s.result ?? null, scene: s.scene ?? null }; })()")


def _js(text: str) -> str:
    return json.dumps(text)[1:-1].replace("'", "\\'").replace("`", "\\`")


def _skips(pt: Playtest) -> tuple[int, int]:
    """Seconds skipped for the HUD and difficulty checks; together they stay below a timed round's length."""
    if pt.round_end.by == "timer" and pt.round_end.seconds:
        total = pt.round_end.seconds
        return max(1, min(5, total // 5)), max(1, min(20, total // 3))
    return 5, 20


def _input_step(i: int, key: str, expect: str) -> str:
    condition, meaning = EXPECT[expect]
    if key == CLICK:
        act = f"""  const target{i} = await page.evaluate(() => {{
    const t = {STATE}?.clickTarget;
    const c = document.querySelector('canvas') as HTMLCanvasElement | null;
    if (!t || !c || typeof t.x !== 'number' || typeof t.y !== 'number') return null;
    return {{ x: t.x * c.clientWidth / c.width, y: t.y * c.clientHeight / c.height }};
  }});
  if (!target{i}) throw new Error('[input] __GAME_STATE__.clickTarget gives no {{x, y}} to click');
  await page.locator('canvas').click({{ position: target{i} }});"""
        release = ""
        label = "a click at __GAME_STATE__.clickTarget"
    else:
        act = f"  await page.keyboard.down('{key}');"
        release = f"  await page.keyboard.up('{key}');"
        label = f"pressing {key}"
    return f"""
  // [input] {label} must {meaning}
  const before{i} = await page.evaluate(() => {SNAPSHOT});
{act}
  try {{
    await page.waitForFunction((before: any) => {{ const now: any = {SNAPSHOT}; return {condition}; }}, before{i},
      {{ timeout: {MOVE_TIMEOUT_MS} }});
  }} catch {{
    throw new Error(`[input] {label} did not {meaning}: before ${{JSON.stringify(before{i}).slice(0, 160)}}, now ${{JSON.stringify(await page.evaluate(() => {SNAPSHOT})).slice(0, 160)}}`);
  }}{" finally {" + chr(10) + "  " + release + chr(10) + "  }" if release else ""}"""


def acceptance_spec(spec: GameSpec, import_from: str = "@playwright/test", quality: bool = True) -> str:
    """TypeScript source of tests/acceptance.spec.ts for `spec` (its playtest, or one derived for old specs).

    `quality=False` keeps only the playing steps (start click, inputs, round end, restart).
    """
    pt = playtest_of(spec)
    title = _js(spec.title.lower())
    hud_skip, difficulty_skip = _skips(pt)
    blocks = []

    if quality:
        blocks.append(f"""
  // [start_screen_explains_controls] title + controls line on the start screen
  const menu = await page.evaluate(() => {TEXTS});
  if (!menu.toLowerCase().includes('{title}')) {{
    throw new Error(`[start_screen_explains_controls] the start screen does not show the title "{_js(spec.title)}"; it shows: ${{menu || '(no text)'}}`);
  }}
  if (!/{CONTROL_WORDS}/i.test(menu)) {{
    throw new Error(`[start_screen_explains_controls] the start screen does not explain the controls; it shows: ${{menu}}`);
  }}""")
    blocks.append(f"""
  // real pointer input on the canvas (never the start hook)
  await page.locator('canvas').click();
  await page.waitForFunction(() => {STATE}?.scene === 'GameScene');
  const hudStart = await page.evaluate(() => {TEXTS});""")

    if pt.player is not None and not pt.player.moves_by_itself:
        blocks.append(f"""
  // [input] with no input the avatar stays where it is (catches fake or animated hooks)
  const still = await page.evaluate(() => {STATE}?.player);
  if (!still || typeof still.x !== 'number' || typeof still.y !== 'number') {{
    throw new Error('[input] __GAME_STATE__.player must give the avatar position {{x, y}}');
  }}
  await page.waitForTimeout({STILL_MS});
  const after = await page.evaluate(() => {STATE}?.player);
  if (after.x !== still.x || after.y !== still.y) throw new Error('[input] the avatar moved with no input');""")
    for i, item in enumerate(pt.inputs):
        blocks.append(_input_step(i, item.input, item.expect))

    if quality and pt.moves_on_its_own:
        blocks.append(f"""
  // [world_alive] something moves on its own. Real play time (no time skipping): spawn timers fire here, so errors
  // inside them reach the browser-error fixture (M21b r13 froze after its first spawn).
  // Snapshots are retaken until some object moves between two of them, so objects that appear later
  // (spawns) count, while objects that never move (frozen spawns, static ground) never do.
  const aliveUntil = Date.now() + {ALIVE_TIMEOUT_MS};
  let alive = false;
  let placed: any[] = [];
  while (!alive && Date.now() < aliveUntil) {{
    placed = await page.evaluate(() => {STATE}?.objects ?? []);
    try {{
      await page.waitForFunction((before: any[]) => (({STATE}?.objects ?? []) as any[]).some(
        (o: any, i: number) => before[i] && (o.x !== before[i].x || o.y !== before[i].y)), placed, {{ timeout: 700 }});
      alive = true;
    }} catch {{
      // nothing moved yet: look again (new objects may have appeared)
    }}
  }}
  if (!alive) {{
    throw new Error(placed.length === 0
      ? '[world_alive] no object appeared within {ALIVE_TIMEOUT_MS // 1000} seconds of play (__GAME_STATE__.objects is empty)'
      : `[world_alive] nothing moves on its own: the objects stay at ${{JSON.stringify(placed).slice(0, 200)}}`);
  }}""")
    blocks.append(f"  await page.screenshot({{ path: '{SHOTS_DIR}/gameplay.png' }});")

    if quality and pt.hud == "time":
        blocks.append(f"""
  // [hud_visible] an on-screen value that changes with game time
  await soon(page, () => {TEXTS}.length > 0, undefined, '[hud_visible] the game scene shows no text (no HUD)');
  const hudBefore = await page.evaluate(() => {TEXTS});
  await page.evaluate(() => (window as any).__TEST_API__.skipTime({hud_skip}));
  await soon(page, (before: string) => {TEXTS} !== before, hudBefore,
    `[hud_visible] the HUD did not change after {hud_skip} seconds of game time; it shows: ${{hudBefore}}`);""")
    elif quality and pt.hud == "input":
        blocks.append(f"""
  // [hud_visible] the on-screen value (score / moves) changed with the inputs above
  await soon(page, (start: string) => {TEXTS}.length > 0 && {TEXTS} !== start, hudStart,
    `[hud_visible] the HUD did not change after the inputs; it shows: ${{hudStart || '(no text)'}}`);""")

    if quality and pt.difficulty_ramps:
        blocks.append(f"""
  // [difficulty_ramps] difficulty grows during the round
  const difficultyBefore = await page.evaluate(() => {STATE}?.difficulty);
  if (typeof difficultyBefore !== 'number') throw new Error('[difficulty_ramps] __GAME_STATE__.difficulty must be a number');
  await page.evaluate(() => (window as any).__TEST_API__.skipTime({difficulty_skip}));
  await soon(page, (before: number) => {STATE}?.difficulty > before, difficultyBefore,
    `[difficulty_ramps] difficulty stayed ${{difficultyBefore}} after {difficulty_skip} seconds of game time`);""")

    if pt.round_end.by == "timer":
        end, how = f"skipTime({pt.round_end.seconds})", f"{pt.round_end.seconds} seconds of game time"
    else:
        end, how = "finishRound('lose')", "__TEST_API__.finishRound('lose')"
    blocks.append(f"""
  // [round_end] deterministic time control only: end the round
  await page.evaluate(() => (window as any).__TEST_API__.{end});
  await soon(page, () => {STATE}?.scene === 'GameOverScene', undefined,
    {json.dumps(f"[round_end] the result screen (GameOverScene) did not appear after {how}")});
  await page.screenshot({{ path: '{SHOTS_DIR}/gameover.png' }});""")
    if quality:
        blocks.append(f"""
  // [feedback_on_events] a readable result screen
  await soon(page, () => {TEXTS}.length > 0, undefined, '[feedback_on_events] the result screen shows no message');""")
    blocks.append(f"""
  // [restart] a real click on the result screen starts a new round
  await page.locator('canvas').click();
  await soon(page, () => {STATE}?.scene === 'GameScene', undefined,
    '[restart] a click on the result screen did not start a new round');""")

    steps = [s for s in ACCEPTANCE_STEPS if f"[{s}]" in "".join(blocks)]
    return f"""import {{ test, expect }} from '{import_from}';

// Generated by agents/generators/acceptance.py from the GameSpec "{_js(spec.title)}" and its playtest plan.
// Locked for the agents. Real input only: pointer clicks and key presses; hooks only read state and
// control time (skipTime / finishRound). Screenshots: {SHOTS_DIR}/.
// Steps (failures start with [step]): {", ".join(steps)}.

async function soon(page: any, fn: any, arg: any, message: string, timeout = {MOVE_TIMEOUT_MS}) {{
  try {{
    await page.waitForFunction(fn, arg, {{ timeout }});
  }} catch {{
    throw new Error(message);
  }}
}}

test('acceptance: play {_js(spec.title)} like a person', async ({{ page }}) => {{
  void expect;
  await page.goto('/');
  await page.waitForFunction(() => {STATE}?.scene === 'StartScene');
  await page.screenshot({{ path: '{SHOTS_DIR}/menu.png' }});
{"".join(blocks)}
}});
"""
