# M21 — Playable generated game (after the roadmap)

Status: complete (2026-10-12): all technical acceptance criteria met by r8 (qwen2.5-coder:32b). The quality bar is M22.

## Why

After M20 no generated Block Dodger was playable. The best run, r2 (9/10), registered keys with `this.input.on('keydown_LEFT', …)`: the pre-3.16 Phaser event name, on the InputPlugin instead of `this.input.keyboard`. Phaser 3.90.0 was installed, so the keys never fired. The tests did not notice, because every movement test called `__TEST_API__.movePlayerLeft/Right()`.

## Acceptance criteria → r8

| Criterion | r8 |
|---|---|
| `npm run build` passes | ✅ |
| all Playwright tests pass (game + acceptance) | ✅ 11/11 on the first test run, no fixer needed |
| browser-error fixture active, no errors | ✅ |
| `menu.png`, `gameplay.png`, `gameover.png` | ✅ `generated/block-dodger-m21-r8/test-results/acceptance/` |
| real ArrowLeft/ArrowRight move the player, no movement without keys | ✅ (`createCursorKeys()`; acceptance spec) |
| graph reaches the human gate | ✅ `needs_human_review`, reviewer `approve` |
| no manual edits in `generated/` | ✅ `scripts/audit_generated.py`: "no manual edits: yes" |

## Steps (as planned, plan v3)

1. **Acceptance spec generator.** `agents/generators/acceptance.py` writes it deterministically from the GameSpec; the file is locked. It uses real input only:
   - a canvas click to start;
   - `page.keyboard.down/up('ArrowLeft'|'ArrowRight')`, with a 300 ms stand-still check;
   - `skipTime(60)` → GameOverScene (time control only);
   - 3 screenshots.

   The applier writes it as `tests/acceptance.spec.ts`.
2. **Baseline proof.** The spec was run on copies of r2 and r6 in the scratchpad; r2 and r6 themselves were not touched.
   - r2 failed at the right step: `ArrowLeft did not move the player: … stayed 240`.
   - r6 failed earlier: it has no position hook.
3. **Browser errors.**
   - Locked `tests/fixtures.ts`: `pageerror` and `console.error` fail the test with "Browser errors:" plus stacks.
   - Favicon `data:,` (no 404 noise).
   - Locked `vite.config.ts`: source maps and no minify only when `GAME_FACTORY_DEBUG_BUILD=1`, which the test runner sets through `run_command(extra_env=…)`. A plain `npm run build` stays minified.
   - `agents/tools/sourcemap.py` (VLQ, best effort) maps `index-*.js:L:C` → `src/…:L`.
   - Test writer: the normalizer rewrites the import to `./fixtures`, and the check requires it.
   - Verified with a deliberate exception: `at TimerEvent.callback (src/scenes/GameScene.ts:13:44 (index-….js:…))`.
4. **Locks and contract.**
   - The fixer rejects locked files (`LOCKED_FILES` + `vite.config.ts`, `tests/fixtures.ts`, `tests/acceptance.spec.ts`).
   - The hook contract adds `playerX`.
   - StartScene must keep `pointerdown` (click to start).
   - The applier writes `.factory/manifest.json` after apply and apply_fix; `scripts/audit_generated.py` checks it.
5. **Fixer anti-repeat.**
   - `FixRecord` in the state.
   - Fingerprint = sha256 of normalized content (whitespace and comment-only lines ignored).
   - Rejected: repeats, no-ops, and whitespace/comment-only changes.
   - Failure signature without numbers or bundle hashes. An applied fix with the same signature is marked `no_effect`, and the next fix must touch other lines.
   - After a no-effect fix the relevant files widen to all `src/` files (24k-char budget). Failures are deduplicated (≤5, ≤1500 chars, 8 frames).
   - The prompt lists the no-effect fixes.
6. **Model config.** `GAME_FACTORY_MODEL` and `--model` (graph CLI, `run_fix_loop.py`); the default stays 14b.
7. **After r7.**
   - The hook contract now checks *defined properties* (`get result()`, `result:`), not any word in the file.
   - The fixer gets deterministic hints: "the failing test reads `__GAME_STATE__.result`, but the hooks do not define it".

## Runs

| Run | Model | Result | Notes |
|---|---|---|---|
| r7 | 14b | 5/9; acceptance ✅ (real keys work), gate reached, audit ✅ | 4 game tests waited for `__GAME_STATE__.result`; test_hooks had renamed it `hitStatus`; the old word-based contract check missed it → properties check + hook hints |
| r7b | 14b | stopped at the test writer | tests used `__GAME_STATE__.blocks`, which no hook defines; repair failed (stricter check, weak model) |
| r8 | 32b | **11/11 first try, 11.7 min**, reviewer approve, gate, audit ✅ | same agent system as r7b |

## Findings

- **The model matters most.** On the same system 32b produced a correct game in one pass, while 14b needed fixes it could not find. M22 uses 32b.
- **The acceptance spec catches the old false positive** (r2) and passed honestly on r7 and r8.
- **"Playable" is not "good".** The user played r7 and called it poor. r8's screenshots show the same level:
  - the start screen is the bare template text "Click to start" with no title (the plan had no StartScene task);
  - a green square on a dark field and no visible timer.

  The reviewer still said "good user experience". This is M22 (quality bar).
- **Test-environment flake:** two template projects started one after another can collide on preview port 41731; it passed when rerun.
- r7b's folder stayed empty and was removed. `generated/block-dodger-m21-r7` and `-r8` are kept (git-ignored).

## Verification log

| Check | Result |
|---|---|
| fast suite | 425 tests OK (18 skipped gated) |
| full gated suite | 425 tests, 634 s: 424 OK + `FixerLLMTest` case `phaser-default` failed (14b returned the file unchanged); rerun 2×: 1 OK, 1 FAIL → a 14b flake on this case (known since M16), not a regression of the M21 checks |
| template real build + tests; deliberate browser error | 3/3; "Browser errors" with `src/scenes/GameScene.ts:13:44` |
