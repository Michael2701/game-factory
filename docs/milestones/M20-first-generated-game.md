# M20 — First Real Generated Game Validation

Status: complete with a **partial result** (2026-10-12) — awaiting user review

## Scope

Generate Block Dodger through the full agent pipeline. No hand-written game code: when a run went wrong, the agent system (prompts, deterministic checks, tools, template) was improved and the run repeated.

The pipeline: idea → planner → decomposer → coder → test writer → apply → test runner → fix loop → reviewer → human gate.

## Done criteria

"The system generates a simple playable browser game project, runs build/tests, fixes at least simple errors, and reaches human review."

| Criterion | Result |
|---|---|
| generates a browser game project | ✅ every run that got past the test writer: template + generated scenes, hooks, tests |
| runs build / tests | ✅ every applied project builds (`build ok`) and runs Playwright |
| fixes simple errors | ✅ fixes applied by the loop: r1 (`children.iterate` → `each`), r2 (3 fixes: 2/10 → 9/10), r3 |
| reaches human review | ✅ r2, r3, r6 stop at `needs_human_review` (state saved, next actions printed) |
| **playable** | ⚠️ **not proven**: no run ended with all tests green. r3 is the first with working keyboard controls |

**Overall: partial.** The pipeline works end to end and stops for the human. The quality of the generated game logic with qwen2.5-coder:14b is not yet enough for an all-green Block Dodger.

## Runs

All runs: `python agents/game_factory_graph.py --fix-loop --target-dir generated/block-dodger-m20[-rN]`; Block Dodger idea; 5 fix attempts. Files changed outside the target: 0 in every run.

| Run | Time | Tests (first → last) | Loop | End | What it showed → agent-system change |
|---|---|---|---|---|---|
| r1 `block-dodger-m20` | 6.3 min | 5/7 → 5/7 | 1 fix applied (`this.children.iterate` → `each`), then a fixer NodeError | `error` (no gate) | ① tests read `__GAME_STATE__.scene` right after an action: the switch happens next frame — **copied from the test writer prompt example**; ② one failed fixer attempt ended the whole loop |
| r2 | 9.6 min | 2/10 → 7/10 → **9/10** | 3 fixes applied, 2 identical-content attempts | ✅ `needs_human_review` | last error: `setVelocity` on a plain rectangle (Phaser API). Controls use `this.input.on('keydown_LEFT')`, Phaser 2 style, **never fires** (also in m19c/r1): nobody could play |
| r3 | 13.3 min | 2/8 → 4/8 | 1 fix, 3 identical-content attempts | ✅ `needs_human_review` | Phaser notes worked: `createCursorKeys()`, rectangles with bodies. New: tests call `__TEST_API__` before the game booted (again as in the prompt example); the template's `scene` getter returned the first active scene; `skipTime` added time |
| r4 | 5.7 min | — | — | `error` at test writer | 10 of 11 tests waited correctly; one racy scene read survived the repair and the strict check rejected the whole output |
| r5 | 4.9 min | — | — | `error` at test writer | the "test the keyboard" rule (added for r4) made qwen use `waitForTimeout(1000)`, which is forbidden → rule removed |
| r6 | 15.2 min | 2/9 → 2/9 | 5 fixes, all the same `testHooks.ts` change | ✅ `needs_human_review` | after `startGame()` GameScene never becomes active (likely an exception in its `create`/`update`). Browser errors are not in the Playwright report, so the fixer cannot see them. Reviewer: "player and blocks are not visible" |

## Changes to the agent system (5 rounds, all with tests)

1. **Test writer example + rule + check:** scenes only via `waitForFunction` (`SCENE_READ`).
2. **Fix loop:** a failed fix attempt (fixer NodeError, no safe fix, apply_fix rejection) costs the attempt instead of ending the graph. When the attempts are exhausted, the run goes to the reviewer and the gate (`_after_fix_attempt`, `_failed_attempt`).
3. **Phaser 3 facts** in the coder and fixer prompts. `phaser_problems` rejects Phaser 2 key events and unloaded textures. The fixer gets `previous_attempts`.
4. **Boot rule:** wait for StartScene before `__TEST_API__` (prompt, example, check). Template changes:
   - the `scene` getter returns the last active scene;
   - no visible placeholder;
   - an `endGame()` pattern.

   The `skipTime` contract was clarified (decrease the time, end the game).
5. **`normalize_tests`:** mechanical rewrite of both races before the check (`invoke_structured(normalize=…)`). It worked in r6: 5 tests got the boot wait. Also, the round-3 keyboard-test rule was removed after it caused the r5 regression.

Files:
- `agents/llm.py` (`normalize`);
- `agents/nodes/{test_writer,coder,fixer}.py`;
- `agents/game_factory_graph.py`;
- `agents/prompts/{test_writer,coder,fixer}.md`;
- `templates/phaser-vite-template/src/{testHooks.ts,scenes/GameScene.ts}`.

Tests:
- `tests/test_phaser_pitfalls.py` (new, 12);
- `test_fix_loop.py` (failed attempts cost an attempt; precondition errors stay fatal);
- `test_test_writer.py`, `test_graph.py`, `test_prompts.py`.

## Generated game (best runs)

- `generated/block-dodger-m20-r2` (9/10). Scenes:
  - StartScene: title + "Click to start";
  - GameScene: falling blocks, 60 s timer, collision → GameOverScene;
  - GameOverScene: message + restart click.

  Hooks: `scene`, `timeLeft`, `result` / `spawnBlockAt`, `movePlayerLeft/Right`, `skipTime`. Limitation: Phaser 2 key events, so it can be won/lost only through the hooks.
- `generated/block-dodger-m20-r3` (4/8): the first with real keyboard controls (`createCursorKeys`) and physics bodies on rectangles.

To look at one: `cd generated/block-dodger-m20-r3 && npm run dev`. The human decision is yours: `python scripts/decide.py --project-dir generated/block-dodger-m20-r3 --show | changes | reject` (approve is refused because the tests failed).

## Verification log

| Check | Result |
|---|---|
| fast suite | 394 tests OK (17 skipped gated) |
| full gated suite (`RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1`) | 394 tests, 709 s: 393 OK + 1 false failure — `test_coder.RunnerTest.test_done_when_command` saw "project files changed during a dry run" because I was writing these docs during the run; re-run alone: **OK** (22 s) |
| template project real build + tests | 3/3 (after the template changes) |

## Limitations

- **qwen2.5-coder:14b is the bottleneck for game logic.**
  - Each run produces a different game.
  - Its correctness depends on Phaser API knowledge the model often lacks.
  - The fixer repeats ineffective changes even when it sees its history.
- **The test writer is a single point of failure.** One repair; a single bad line ends the run before the loop (r4, r5). The normalizer covers only the two known races.
- **The fixer is blind to runtime exceptions:** browser `pageerror` / console errors are not in the Playwright JSON (r6).
- **Tests prove the hooks, not human playability:** controls are driven through `__TEST_API__`.
- Runs take 5–15 minutes; the results vary between runs.

## Next steps (not started)

1. **Capture browser errors for the fixer:** a Playwright fixture in the template that fails a test on `pageerror` / console error, so the report names the exception and the source line.
2. **Fixer anti-repeat:** reject a proposal identical to an earlier attempt, and widen the relevant files to the scene the failing hook calls into.
3. **Test writer:** retry the node once with a fresh call when repair fails, or add more mechanical normalizers.
4. **Template:** a playable placeholder (cursor-key player + body velocity) that the coder extends, instead of Phaser idioms only in prompts.
5. **Model:** try a stronger local model for coder and fixer; the graph already injects `llm`.
6. **The note from `decide.py changes`** could become input to the coder/fixer (M18 finding).

## Run outputs

`generated/block-dodger-m20`, `-r2`, `-r3`, `-r6` are kept (git-ignored). The r4/r5 folders stayed empty (the run stopped before apply) and were removed.
