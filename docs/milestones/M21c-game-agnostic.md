# M21c — Game-agnostic factory: games from any description

Status: **in progress** (2026-10-15).
- The code and the deterministic proof are done.
- Real runs: clicker-1 succeeded (playable, waiting for the user to play). jumper and dodger were not started, because the user had to leave at 16:00. They are the next step.

## Why
The user: "it is a game factory, not a dodger factory; it must make games from a description".

All M21b runs used the Block Dodger idea. Two code audits found 60+ places where the pipeline was a fixed dodger checklist:
- the locked acceptance test always required `playerX` + left/right arrows, falling `hazards`, a growing `difficulty` and game over after `skipTime(60)`;
- `HOOK_CONTRACT` forced `playerX`/`difficulty`/`hazards` on every game;
- the reviewer checks and the fix-loop ranking mirrored those steps;
- the prompts carried a dodger "skeleton" and dodger examples;
- `QUALITY_BAR` and the template were dodger-flavoured;
- `run_fix_loop.py` and `run_fixer_dry_run.py` used the Block Dodger spec for any project.

## Design: a per-game playtest plan
- **`GameSpec.playtest`** (`agents/schemas/game_spec.py`). The planner writes it; code normalizes and checks it (`agents/generators/playtest.py`, as the planner's `normalize`/`check` with one repair). Fields:
  - `player`: null | {moves_by_itself}
  - `inputs`: key name or "Click" → `player_left/right/up/down` | `score_up` | `state_changes`
  - `moves_on_its_own`
  - `hud`: time | input | none
  - `difficulty_ramps`
  - `round_end`: timer N s | hook

  Checks: every input is one of the `controls`, timer seconds match the win/lose text, and avatar moves need an avatar. Key names are normalized ("Left Arrow", "←" → ArrowLeft; "Mouse click" → Click).
- **Acceptance per game** (`agents/generators/acceptance.py`).
  - Only the needed steps, in the generic order start → input → world_alive → hud → difficulty → round_end → feedback → restart.
  - Clicks go to the game-reported `__GAME_STATE__.clickTarget`; start and restart click the canvas centre (no fixed point).
  - The stillness check runs only for an avatar that waits for input.
  - Skipped time stays inside a timed round.
  - `[world_alive]` retakes snapshots until something moves, so later spawns count while frozen objects never do.
  - Specs written before M21c get a derived playtest.
- **Hook contract from the playtest**:
  - always: scene, result, texts, objects, startGame, skipTime, finishRound;
  - plus player / score / difficulty / clickTarget as the game needs.

  The coder check, the coder prompt (`{{playtest}}`: what the test will do with THIS game) and the GameScene member check (`this.player`, `this.score`, `clickTarget`, …) all use it.
- **Generic template**:
  - `testHooks.ts` reads GameScene members (player, score, difficulty, clickTarget), all visible non-text `objects`, and `finishRound`;
  - a finished `GameOverScene`;
  - a neutral GameScene placeholder;
  - PALETTE by role (primary/secondary/danger/good/accent).
- **Quality bar per game**:
  - the universal items, plus "gets harder" only when the playtest says so;
  - the reviewer must pass checks the game's acceptance has no step for as **not applicable**, and must not pass unreached ones (**not verified**).
- **Prompts genre-neutral**:
  - planner/decomposer/coder/test-writer examples are a memory game and a maze, deliberately unlike the validation ideas;
  - the coder's dodger skeleton was replaced by general Phaser API facts;
  - the fixer/reviewer wording is neutral.
- **Scripts** use the project's saved spec (`human_gate.saved_spec_and_plan`).
- **New deterministic check** (found in clicker-1, also seen in M21b r10): ui.ts helpers (`PALETTE`, `hud`, `flash`…) used without importing them. The whole file is checked, so the fixer's added lines don't give false alarms.

## Deterministic proof (no LLM)
- `agents/fixtures/playtest_games.py`: hand-written **Target Pop** (mouse clicker, score, 30 s timer) and **Hop Over** (Space jumper, sliding obstacles, difficulty, no timer).
  - Both pass their own generated acceptance test.
  - Each broken variant fails at its step: no score → `[input]`, no jump → `[input]`, frozen obstacles → `[world_alive]`. See `tests/test_playtest_games.py` (npm-gated).
- Generator unit tests for 5 genres (dodger, clicker, jumper, snake, memory) in `tests/test_acceptance.py`.
- Real planner, three different ideas: each gets a sensible, different playtest.
  - clicker: no avatar, Click → score_up, timer 30;
  - jumper: Space → player_up, moves on its own, hook;
  - dodger: arrows, timer 60.
- Suite: 486 tests OK with `RUN_NPM_TESTS=1` (11 skipped: Ollama-gated). Before the ui-import check: fast suite green; docs links need this file.

## Real runs (qwen3:30b-a3b, logged in logs/runs/)
| Run | Idea | Result |
|---|---|---|
| m21c-clicker-1 | "Click the targets that pop up; 15 hits within 30 seconds" | **5/5, reviewer approve, audit clean, playable** (21 min). Spec → 5 tasks → code → tests all clean. The first test run caught `ReferenceError: PALETTE is not defined` (browser-error fixture; the new ui-import check now prevents this). Fix #1 used a wrong import path and broke the build → **reverted automatically**. Fix #2 → 2/5, fix #3 → 3/5, fix #4 made the generated test compare a float timer with `toBeCloseTo(30, 1)` instead of `toBe(30)` (legitimate) → 5/5. **Browser check by Claude**: 5 real clicks → score 5, the target jumps to a new place each time, the timer counts down, no page errors. Waiting for the user to play. |
| m21c-jumper-1 | "Jump over obstacles with the Space bar; clear 20 obstacles" | not run yet |
| m21c-dodger-1 | Block Dodger (regression) | not run yet |

## Next steps
1. The user plays clicker-1: `cd generated/m21c-clicker-1 && npm run dev`, then `python scripts/decide.py --project-dir generated/m21c-clicker-1 approve|changes --note "…"|reject`.
2. Run jumper-1 and dodger-1:
   `python agents/game_factory_graph.py "<idea>" --fix-loop --target-dir generated/m21c-<name>-1 --run-id m21c-<name>-1`.
   At most 2 runs per idea; agent-system fixes only between runs.
3. Per idea: its own acceptance green, audit clean, a browser check by Claude, then the user plays. Honest report here, then STOP (plan-2 M22 only on the user's word).
