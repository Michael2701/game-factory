# M17 — Reviewer Node

Status: complete (2026-10-12)

## Scope

`reviewer_node`: GameSpec + files summary + TestResult → structured `ReviewResult` (scope, testability, hooks, browser suitability, UX, file organization). It runs after the fix loop. It changes no files and leaves `status` unchanged: mapping the verdict to `needs_human_review` / `approved` / … is M18.

## Done criteria

The node returns a structured ReviewResult. **Met:**
- Real qwen2.5-coder:14b reviews pass the schema and the semantic check:
  - the passing fixture;
  - a build failure (`reject`);
  - `generated/fix-demo-two-bugs`;
  - `generated/block-dodger`;
  - the full fix loop + review on the two-bugs fixture.
- The reviewer changed no file (hash proof).

## Graph

```
… apply_changes → test_runner ─┬─ passed / attempts used up → reviewer → END
                    ▲          ├─ error → END (no review)
                    │          └─ failed, attempts left → fixer → apply_fix ─┐
                    └─────────────────────────────────────────────────────────┘
build_fix_loop_graph: START → test_runner → (same loop + reviewer)
```

## Changes

- `agents/nodes/reviewer.py` (new):
  - `REVIEW_CHECKS`: the 6 check names.
  - `review_facts`: deterministic ground truth. Covers build ok (None when the build did not run), test status / `x/y`, test count, hooks defined in `src/` and used in `tests/`, scene classes outside `src/scenes/`, and stray files (anything but known root config files, `src/`, `tests/`, `public/`).
  - `files_summary`: the full tree with line counts, then file contents up to 16k chars (src first, then specs, then the rest); omitted files are listed.
  - `check_review`:
    - exactly the 6 checks, in order;
    - `approve` ⇔ every check passed **and** tests passed;
    - build failed → `browser_game_suitable` false and verdict `reject`;
    - `test_hooks_present` must equal the fact;
    - layout facts → `files_organized` false;
    - a non-approve verdict needs ≥ 1 issue;
    - issues and check notes may name a file outside the tree only to say it is missing. Suggestions may name new files.
  - `review` (`invoke_structured` → one repair).
  - `reviewer_node`: needs `game_spec`, `test_result` and `target_dir` (otherwise error with no LLM call); reads read-only; sets `review_result`; keeps `status`.
- `agents/prompts/reviewer.md`:
  - new `{{facts}}` block ("ground truth") and rules tying checks and verdict to the facts;
  - missing files must be reported as `<path>: missing`;
  - `scope_small` fails only for extra features;
  - **the example now reviews a different game** with a "never copy" line (see findings).
- `agents/game_factory_graph.py`:
  - `_after_test` → `reviewer` on passed / exhausted;
  - `REVIEW_NODES`;
  - `format_review` prints `=== REVIEW ===`;
  - `recursion_limit` +1;
  - the docstring.
- `scripts/run_reviewer.py` (new): `--project-dir` (existing folder below `generated/`/`games/`), `--spec` (default: sample Block Dodger spec), `--json`. It runs the real test runner, then the reviewer, and prints facts, review and "files changed by the reviewer". Exit 0 / 1 (reviewer error) / 2 (usage).
- `scripts/run_fix_loop.py`: prints the review.
- Tests:
  - `tests/test_reviewer.py` (new; 35 fast + 2 gated).
  - `tests/test_fix_loop.py`: scripted replies end with a review; structure, recursion limit, and "runner error → no review".
  - `tests/test_prompts.py`: `facts` variable.
- Docs: ARCHITECTURE, NODES, PROMPTS (variables + qwen findings), TESTING, ROADMAP, README, CLAUDE.md, this file.

## Real runs

`python scripts/run_reviewer.py --project-dir generated/fix-demo-two-bugs` (exit 0, 21 s; tests 3/3 passed). The fixture is a deliberately minimal game, so the review is correct:

```
verdict: needs_changes
  FAIL  scope_small           The game lacks controls for moving left/right and does not handle collisions with blocks.
  FAIL  testable              Win/lose conditions and controls cannot be checked by automated tests as they are not implemented.
  PASS  test_hooks_present    Hooks set in src/testHooks.ts and read by the tests.
  PASS  browser_game_suitable Build and all tests passed.
  FAIL  no_obvious_ux_issues  There is no visible feedback on win/lose, and no way to restart the game.
  PASS  files_organized       Scenes in src/scenes, tests in tests/.
  issue: src/scenes/GameScene.ts: missing move left/right controls
  issue: src/scenes/GameScene.ts: missing collision detection with blocks
  …
files changed by the reviewer: 0
```

`python scripts/run_reviewer.py --project-dir generated/block-dodger` (exit 0, 24 s; tests failed, "0/0": Playwright cannot parse the spec):

```
verdict: needs_changes
  PASS  … (all 6)
  issue: tests/game.spec.ts: Missing semicolon at line 58
```

This is accurate: Playwright reports `SyntaxError: Missing semicolon. (58:116)`, the stray `)` the M16 fixer could not see. The verdict follows the rule "tests did not pass → not approve".

`python scripts/run_fix_loop.py --case two-bugs --target-dir generated/fix-demo-two-bugs-m17` (exit 0, 75 s):
- 2 fix rounds, then tests pass 3/3;
- then `=== REVIEW ===` with verdict `needs_changes` (no movement/collision, no GameOverScene: "src/scenes/GameOverScene.ts: missing win/lose message and restart functionality");
- files changed outside the project: 0.

## Verification log

| Check | Result |
|---|---|
| fast suite | 333 tests OK (16 skipped gated), 6.1 s |
| `RUN_OLLAMA_TESTS=1 … test_reviewer.RealModelTest` | first run 1/2: the copied example was caught by the path check, and repair then emptied `issues`. After the prompt fix and the missing-file rule: **2/2** |
| full gated suite (`RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1`) | **333 tests OK, 0 skipped**, 653 s: real reviewer tests, real two-bugs loop (now with review), real fixtures, M13 e2e |
| validate_schemas / smoke_graph | ok (9 models) / exit 0, sha256 = baseline `e0ff1d10…` |

## Findings / issues

- **qwen copies the prompt example.** On the passing fixture the first real review was the prompt example almost word for word, including the non-existent `src/scenes/GameOverScene.ts`. `check_review` rejected the path. On repair, qwen emptied `issues`, which broke the "non-approve needs an issue" rule, so it ended in a NodeError. Fix:
  - the example now reviews a clearly different game (coin catcher, `BasketScene.ts`) and says "never copy";
  - a test asserts that a verbatim copy is caught.

  The same risk likely applies to other prompts with concrete examples.
- **Missing files are legitimate issues.** After the example fix, qwen correctly complained that the GameSpec's `GameOverScene` does not exist. The strict "only existing paths" rule rejected that, so it was relaxed: an unknown path is fine when the text says it is missing.
- **`scope_small` is misused:** qwen fails it for *missing* features (it should only fail for *extra* ones), even after a clarifying rule. This cannot be checked deterministically. The human gate (M18) sees the notes; a candidate fix is renaming the check or splitting "spec coverage" into its own check.
- **The fixture project is a stub**, so a correct review is `needs_changes`, not `approve`. A real `approve` needs a complete game (M19/M20). With FakeLLM, `approve` is covered for the graph and CLI.
- **The verdict depends on tests:** when tests fail (block-dodger), the verdict cannot be `approve` even if the model rates all 6 checks as passed. That is intended. The issue then names the actual failure.
- `generated/fix-demo-two-bugs-m17` is kept as a run output, like the M16 demos.
