# Prompts reference

Prompt templates for each agent role live in `agents/prompts/*.md`; the loader is `agents/prompts/__init__.py`.

## Loader API

```python
from agents.prompts import render_prompt, load_prompt, prompt_variables, PROMPT_NAMES
from agents.schemas import GameSpec

text = render_prompt("planner", idea="...", schema=GameSpec.model_json_schema())
```

- Placeholders are `{{name}}` (lowercase + `_`). Double braces because prompts contain JSON.
- `render_prompt` is strict: a missing variable, an unknown variable → `ValueError`. Only names in `PROMPT_NAMES` can be loaded.
- Values: `str` is inserted as is; Pydantic models → `model_dump_json(indent=2, exclude_none=True)`; anything else (dict/list/int) → `json.dumps(indent=2)`.
- `{{schema}}` is always the live `model_json_schema()` of the output model, so prompts cannot drift from `agents/schemas` ([SCHEMAS.md](SCHEMAS.md)).

## Prompts

| Prompt | Variables | `{{schema}}` model | Expected output |
|---|---|---|---|
| `planner` | idea, schema | `GameSpec` | `GameSpec` |
| `task_decomposer` | game_spec, project_base (M19: template guide or "starts EMPTY" steps), schema | `TaskPlan` | `TaskPlan` (5–12 ordered tasks) |
| `coder` | task, game_spec, allowed_paths, optional_paths, locked_paths (M19), existing_files, schema | `FileChangeSet` | `FileChangeSet` (one change per allowed path; optional updates of integration files; hook contract for test_hooks tasks) |
| `test_writer` | game_spec, project_files, schema | `FileChangeSet` | `FileChangeSet` with `tests/game.spec.ts` |
| `fixer` | test_result (compact: failed commands + failure messages), project_tree (all paths), relevant_files, new_files, game_spec, task_plan, fix_attempt, max_fix_attempts, schema | `FileChangeSet` | `FileChangeSet` — minimal update(s) of relevant files; may be empty = no safe fix (M15) |
| `reviewer` | game_spec, files_summary, test_result, facts, schema | `ReviewResult` | `ReviewResult` with 6 fixed checks |
| `repair` | raw_output, errors, schema | model being repaired | the same object, fixed (used by every node's one repair attempt, M4) |

Reviewer check names (in order): `scope_small`, `testable`, `test_hooks_present`, `browser_game_suitable`, `no_obvious_ux_issues`, `files_organized`.

The `{"changes": [...]}` wrapper is `FileChangeSet` (M8). coder, test_writer and fixer inject its schema.

File contents passed into prompts (`existing_files`, `project_files`, `relevant_files`) must be rendered with `format_files({path: content})` — readable `=== path ===` blocks, no JSON escaping, no markdown fences.

## Structure of every prompt

`## Role` → `## Input` (placeholders) → `## Rules` → `## Output format` → `## Example output` (one ```json block).

Writing rules:
- Output section always says `Return ONLY one JSON object` and `no extra fields`.
- Rules emphasise small scope, testability (`window.__GAME_STATE__`, `window.__TEST_API__`), and safety.
- File-writing prompts (coder, test_writer, fixer) must contain: `do not write files yourself`, `Never use absolute paths, "~", or ".."`, no shell commands, no secrets.
- The example JSON must validate against the expected output model (enforced by tests).

## Known model behaviour (qwen2.5-coder:14b)

- It usually wraps JSON in ```` ```json ```` fences despite the instruction → always parse with `agents.llm.extract_json` / `parse_model` (handles fences and surrounding prose).
- In code inside JSON strings it sometimes writes JS escapes such as `\'` (`'player\'s'`) or `\d`, which are invalid JSON; the repair call usually repeats them. `extract_json` keeps their backslash (`fix_invalid_escapes`: `\'` → `\\'`), which is exactly the code the model meant. Found in M14 as the cause of an intermittent test_writer failure in the real e2e run.
- The repair prompt only sees the previous output and the error list, never the project files. So a semantic check error must carry the context needed to fix it. Example: the test writer's "hooks not defined" error includes the hook files' content and says "change only the test code … keep this change's path and operation" (without that, qwen switched `create` to `update`). The repair prompt allows changing content where an error lists what is available.
- **It copies prompt examples almost verbatim when the input matches the example.** Never use the validation game (Block Dodger) as a prompt example; the planner, task_decomposer, coder, test_writer and fixer examples are "Target Tapper".
- Test writer (M11): without explicit rules it waited for timers in real time, waited for game over without causing it, asserted only the scene and duplicated tests → the prompt now requires `skipTime(seconds)`, causing every awaited state, asserting `result`, no duplicates. Static `check_tests` cannot catch semantics.
- Fixer (M15): with only the relevant files it could not fix a casing error in an import path (it never saw that the file is `GameScene.ts`) → the prompt also gets `project_tree` (all paths, no content). On the synthetic cases and the real M14 build error it proposed one-line fixes (`import * as Phaser from 'phaser'`, `./scenes/GameScene`), 6/6 in the gated test runs.
- Fixer (M16):
  - On a Playwright timeout (`win-logic`), one real run "fixed" the test by raising `timeout` in playwright.config.ts instead of fixing `timeLeft < 0`. Now:
    - `playwright.config.ts` is relevant only when the failure names it;
    - `check_fix` rejects added lines with timeout/waits in tests and the config;
    - the prompt says a timeout means the state was never reached.
  - After the change, the real model fixed every case in 29 of 30 runs. The one miss: `content: null` for an update, twice. Repair cannot fill in content it never saw, so the node returns a NodeError and the loop stops (known flake, roughly 1 in 30).
  - In the real loop, qwen found runtime bugs from the Playwright failure alone (whole project relevant).
  - It could not spot a stray `)` in a 100-line spec (block-dodger) and returned the file unchanged.
- Reviewer (M17):
  - With a concrete example in the prompt, qwen **copied it almost verbatim**, including a file that did not exist (`src/scenes/GameOverScene.ts`); on repair it emptied `issues` instead of naming a real file. Now the example reviews a clearly different game (coin catcher, `BasketScene.ts`) with a "never copy" line, and `check_review` rejects unknown file paths (a test checks that the copied example is caught).
  - It names files the spec needs but the project lacks; that is allowed when the text says the file is missing.
  - It fails `scope_small` for *missing* features although the check is about *extra* features, even after a clarifying rule. Not enforceable deterministically; the human gate (M18) sees the notes.
- End-to-end (M13): without the hook contract the coder omitted `result`, and a scenes task wrote test hooks into main.ts while the hooks task wrote a second, unused copy; the test writer used hooks nobody defined. Deterministic checks (hook contract, hooks-must-exist) + "only your own task" fixed it in the next real run.
- Without explicit rules it produced identical win/lose conditions and vague goals ("a certain length"); the planner prompt now demands exact numbers and different win/lose conditions.

## Changing a prompt

1. Edit the `.md` file; keep the 5 sections and placeholder names.
2. If variables change, update `EXPECTED_VARIABLES` in `tests/test_prompts.py` and the table above.
3. Run `python -m unittest discover -s tests -v`, and with `RUN_OLLAMA_TESTS=1` for the planner LLM check.
- Template (M19): the task_decomposer and coder examples now start from the Phaser template (Target Tapper: update StartScene/GameScene, create GameOverScene; coder example creates GameOverScene and updates the template's main.ts). The coder prompt forbids `import Phaser from 'phaser'` and `check_changes` enforces it (M14 build failure).
- **Prompt examples are copied, bugs included (M20).** The test writer example read `__GAME_STATE__.scene` right after an action and called `__TEST_API__` before the game booted; qwen reproduced both in every Block Dodger run. Both examples are fixed, and `normalize_tests` rewrites the two races mechanically, because even after the fix one racy line in 11 tests sank a whole run.
- **A new rule can cause a new violation (M20 r5).** "Test one control with real keyboard input" made qwen add `waitForTimeout(1000)`, which `check_tests` forbids, so the run stopped at the test writer; the rule was removed.
- **Phaser 2 idioms (M20).** Without explicit notes, qwen wrote `this.input.on('keydown_LEFT')` (never fires in Phaser 3: nobody can play), sprites with unloaded textures, and `setVelocity` on plain rectangles. The coder and fixer prompts now carry "Phaser 3 facts" and `phaser_problems` rejects the first two.
- **The fixer repeats itself (M20).** Even with `previous_attempts` in the prompt it proposed the same `testHooks.ts` change five times in r6 and identical-content changes in r2/r3.
