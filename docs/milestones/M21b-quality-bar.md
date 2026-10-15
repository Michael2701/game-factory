# M21b — Quality bar, run log and fix-loop hardening (after M21)

Status: complete as **infrastructure**, partial as a **result**. The quality checks, run log, model limits and revert all work and are tested. None of the four Block Dodger runs (r10–r13, qwen3:30b-a3b) produced a game that was really playable. r13 passed every check but was unplayable, and that exposed the last gap (`[world_alive]`).

M21b also showed the system had been tuned for one game. Making it game-agnostic is M21c ([M21c-game-agnostic.md](M21c-game-agnostic.md)).

Originally numbered M22. It was renamed because `plan-2.md` uses M22–M36 for the platform (backend, Studio, portal).

## Why

The user played r7 (M21) and said the game was "as if a 5-year-old made it". Every check measured "works", none measured quality.

## What was built

| Area | What | Where |
|---|---|---|
| Quality bar | Planner adds `quality_requirements`: HUD, difficulty, feedback, start screen, restart, colours | `agents/nodes/planner.py` |
| | Acceptance quality steps (`[hud_visible]`, `[difficulty_ramps]`, …) | `agents/generators/acceptance.py` |
| | Look helpers | `templates/…/src/ui.ts` |
| | `decide.py changes --note` → `run_fix_loop.py --from-decision` sends the human's note to the fixer | `scripts/run_fix_loop.py` |
| Reviewer | Quality checks are decided by acceptance facts | `agents/nodes/reviewer.py` |
| | **Not verified ≠ passed**: a check the acceptance test never reached must be `passed: false` | `quality_coverage` |
| Model | `GAME_FACTORY_MODEL` in a git-ignored `.env`. Priority: `--model` > env var > `.env` > fallback `qwen3:30b-a3b` | `agents/llm.py`, `.env.example` |
| | `agents/smoke_graph.py` (frozen) model line changed with the user's OK | |
| | `reasoning=True` keeps qwen3's thinking separate from the JSON | |
| | `<think>` blocks are stripped | |
| Limits | 16 384 tokens and 900 s per LLM call; a cut-off reply fails the attempt with a "think less" repair hint | `MAX_TOKENS`, `CALL_TIMEOUT_S` |
| | (r11 fixer reasoned for 54 600 tokens / 26 min and never ended) | |
| Run log | `logs/runs/<run-id>/run.log` (one line per node / LLM call, `tail -f`) and `events.jsonl` | `agents/run_log.py` |
| | `llm/NNN-<node>.md`: prompt, **model reasoning**, reply, errors, repair | |
| | Viewer `scripts/show_run.py <id> [--follow] [--llm N]` | |
| Revert | A fix that makes the next test run worse is undone, ranked by (build ok, acceptance progress, tests passed) | `game_factory_graph.made_worse` |
| | No line blocking after a revert; an exact repeat is still refused | |
| Deterministic Phaser checks | `this.time.deltaTime` / `.delta` / `.add()` (invented, NaN/TypeError) | `phaser_problems` (coder + fixer) |
| | `body.on(...)` (no body events) | |
| | velocity set before adding to a physics group (reset to 0) | |
| | Game scene: keyboard input for key controls; a lose handler that is never registered | `gameplay_problems` |
| `[world_alive]` | Acceptance waits up to 4 s of **real** time for something to move on its own, so spawn timers and errors inside them run | `acceptance.py` |
| | (r13's tests finished before the first spawn) | |

## Runs (qwen3:30b-a3b, Block Dodger idea)

| Run | Result | What it showed → what changed |
|---|---|---|
| r10 | 0/4, needs_changes | Fix #3 reached 3/4. Fix #4 invented `this.time.add(seconds)` → 0/4 and stayed. **Revert** added. The reviewer had marked unreached quality checks PASS → **not verified** rule. Import-path and clock hints added to the prompts. |
| r11 | stopped by hand | Coder used `this.time.deltaTime` (NaN HUD). Fixer reasoning never ended (54 600 tokens). **Token and time limits** added. |
| r12 | 3/6 | Count-based revert undid a correct fix (`[controls]` → `[hud_visible]`, 3/6 → 2/6), then line blocking stopped the fixer. Revert now ranks **acceptance progress** first, without line blocking. On a scratchpad copy: fix #2 plus one line (`update(_t, delta)`) → acceptance fully green. **Deterministic clock / keyboard / lose-handler checks** added. |
| r13 | 4/4, approve, audit clean, **but unplayable** | Blocks never fell: `block.body.on(...)` threw in the spawn timer and froze the loop, and velocity was set before `group.add` (reset to 0). The tests ended before the first spawn. **`[world_alive]`** and both deterministic checks added. Proof on copies: new acceptance fails r13, passes after the 2-line fix. |

Every run was logged and audited; there were no manual edits in `generated/`. Nothing was approved, because no run produced a playable game.

## Lessons
- "Green" must include *something happens in real time*: tests that only skip time miss timer-driven code entirely.
- Prompt hints alone do not stop repeated API hallucinations. Deterministic checks with a precise repair message do (r10–r13 → 0 repeats in the checked code).
- A revert needs a progress measure, not a test count.
- All runs used one idea, and the fixes started to encode that idea. That is why M21c follows.

## Tests
Fast suite plus `RUN_NPM_TESTS=1`; counts are in the M21c report, which builds on this. New test files:
- `test_run_log.py`
- `test_model_config.py` (limits, `.env`)
- `test_gameplay_checks.py`
- revert tests in `test_fix_loop.py`
- quality tests in `test_quality_bar.py`
