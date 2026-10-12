# Agent nodes

Conventions for LangGraph nodes in `agents/nodes/`. The planner (`agents/nodes/planner.py`, M4) is the reference implementation — copy its shape for new LLM nodes.

## Shape of an LLM node

```python
def do_work(inputs..., llm=None) -> OutputModel | NodeError:   # pure-ish core, never raises
    ...

def <name>_node(state: GameFactoryState, llm=None) -> dict:      # LangGraph wrapper
    result = do_work(..., llm=llm)
    if isinstance(result, NodeError):
        return {"status": FactoryStatus.ERROR, "error": f"<name>: {result.model_dump_json()}"}
    return {"<field>": result, "status": FactoryStatus.<NEXT>, "error": None}
```

- **Return partial state updates** (dicts), not a whole state.
- **`llm` is injectable**; default `agents.llm.make_llm()` (`qwen2.5-coder:14b`, temperature 0.2). Tests pass a fake.
- **Never raise** for expected failures: invalid input, invalid model output, LLM/Ollama unavailable → `NodeError` ([SCHEMAS.md](SCHEMAS.md)).
- In a graph, bind the llm with a lambda: `graph.add_node("planner", lambda s: planner_node(s, llm=llm))` — see `build_graph` in `agents/game_factory_graph.py` and the Graph section of [ARCHITECTURE.md](ARCHITECTURE.md).

## Parse → check → repair → error flow

Implemented once in `agents.llm.invoke_structured(llm, node, prompt, Model, schema, check=None)` — nodes call it instead of re-implementing the loop:

```python
schema = TaskPlan.model_json_schema()
prompt = render_prompt("task_decomposer", game_spec=spec, schema=schema)
return invoke_structured(llm or make_llm(), NODE, prompt, TaskPlan, schema,
                         check=lambda plan: check_plan(plan, spec))
```

1. The node validates its input first (e.g. `GameIdea`, `state.game_spec is not None`) — invalid → `NodeError`, **no LLM call**.
2. `llm.invoke(prompt)` → `parse_model(raw, Model)` (`extract_json` strips ```` ``` ```` fences and prose and keeps the backslash of JS-style escapes such as `\'` that are invalid JSON, then strict Pydantic validation).
3. If parsing passed, the optional **semantic `check(result) -> list[str]`** runs (rules the schema cannot express, e.g. "game_slug must equal spec.slug", "plan needs a build task"). Non-empty list = invalid.
4. Any errors (schema or semantic) → **one** repair call with the `repair` prompt (`raw_output`, errors as `- field.path: msg` lines, `schema`) → parse + check again.
5. Still invalid → `NodeError(message="model output is not a valid <Model> after repair", attempts=2, validation_errors, raw_output)`.
6. Exception from the LLM call (e.g. Ollama down) → `NodeError(message="LLM call failed: <Type>: <msg>")`.

Files shown to the LLM (existing/relevant/project files) go through `agents.prompts.format_files({path: content})` — never as JSON (escaped newlines are unreadable for code).

Write semantic check messages as `field: what is wrong and what is expected` — they are shown to the LLM verbatim in the repair prompt. `format_errors(exc)` formats exceptions the same way.

## Cross-task coherence (M13)

Nodes that write code for several tasks must keep them consistent:

1. **Virtual file system** — `coder_dry_run_node` codes tasks in plan order; each task gets every file proposed so far as `existing_files` (`merge_changes`), so it imports real names and uses `update` for existing files.
2. **Integration files** — `INTEGRATION_FILES = ("src/main.ts",)`: once a file exists, later tasks may *update* it via `optional_paths` (register scenes, install hooks). They are optional and can never be created this way. Prompt rule: do only your own task there.
3. **Ownership** — `tests` tasks are skipped by the coder in the graph; the test writer owns `tests/game.spec.ts`.
4. **Hook contract** — a `test_hooks` task must expose `HOOK_CONTRACT` (`__GAME_STATE__.scene/.result`, `__TEST_API__.startGame()/.skipTime(seconds)`) plus the spec's hooks (checked); the test writer runs last and may only use hooks defined in the project's hook files (checked lexically).

## Deterministic nodes

Not every node calls the LLM: `test_runner` (M12) only runs safe commands and `applier` (M14) only writes through `apply_changes`. It still follows the node shape (core function + `<name>_node(state)` returning a partial update) and never raises for expected failures — they become `TestResult(status="error")`.

## Runner scripts

`scripts/run_<node>.py` — CLI around the core function: print the result model as JSON; exit 0 on success, 1 on `NodeError`, 2 on usage error. Insert the project root into `sys.path` (see `scripts/run_planner.py`).

## Testing a node

- Deterministic tests use the scripted `FakeLLM` from `tests/fakes.py`: returns replies in order, records prompts, raises replies that are exceptions.
- Cover: semantic check rules directly (incl. that the prompt's example passes them), valid first try, fenced/prose output, repair success (2 calls, errors in repair prompt), repair failure → NodeError, LLM exception, invalid input → 0 calls, node state update, node inside a `StateGraph`, runner exit codes.
- Real-model check: gated by `RUN_OLLAMA_TESTS=1`, assert the output validates (structure), not exact text.

## Nodes

| Node | File | Input → Output | Status |
|---|---|---|---|
| planner | `agents/nodes/planner.py` | idea → `GameSpec` (`plan_game`, `planner_node`) | exists (M4) |
| task_decomposer | `agents/nodes/task_decomposer.py` | `GameSpec` → `TaskPlan` (`decompose`, `check_plan`, `task_decomposer_node`); never writes files; M19: `decompose(spec, llm, template)` renders `project_base` (template guide); with a template `check_plan` needs no `config` task and rejects locked template files in `target_files` | exists (M5) |
| coder | `agents/nodes/coder.py` | task + spec + existing files → `FileChangeSet` (`code_task`, `check_changes`, `is_coder_task`, `merge_changes`); graph node `coder_dry_run_node` (M13); never writes; M19: the virtual file system starts from `project_base(state.template, …)` (the instantiated template; proposals never contain it), `check_changes(…, locked_paths)` rejects changes to locked template files, and always rejects `import Phaser from 'phaser'` | exists (M8, M13) |
| test_writer | `agents/nodes/test_writer.py` | spec + project files → `FileChangeSet` with `tests/game.spec.ts` (`write_tests`, `check_tests`: imports, determinism, ≥3 tests, hooks must exist); graph node `test_writer_dry_run_node` (M13); never writes; M19: sees template + coder proposals (the template's `tests/game.spec.ts` is replaced by an update; `playwright.config.ts` exists, so it is never created) | exists (M11, M13) |
| applier | `agents/nodes/applier.py` | proposals → files in `state.target_dir` (`final_changes`: merge the template (M19), code and tests into one `create` per file; `check_target`: new/empty folder below `generated/` or `games/`; `apply_node`: preview → all-or-nothing write, sets `target_dir`, `changed_files`, `changes_applied`; refusals start with `applier: target refused`); deterministic, no LLM; graph only with `--apply`. Fix loop (M16): `apply_fix_node` applies `state.fix_changes` inside the EXISTING `target_dir` (`check_fix_target`: existing folder below `generated/`/`games/`), preview → all-or-nothing, clears `fix_changes`, adds to `changed_files`, status `testing`; errors start with `apply_fix:` | exists (M14, M16) |
| test_runner | `agents/nodes/test_runner.py` | project dir → `TestResult` (`run_project_checks`, `parse_playwright_json`, `test_runner_node`); deterministic, no LLM; install → build → `npx playwright test --reporter=json` (only if `tests/*.spec.ts` exist), stops at first failure; the node tests `project_dir`, else `state.target_dir` (M16), else `generated/<slug>` | exists (M12, M16) |
| fixer | `agents/nodes/fixer.py` | failed `TestResult` + project files → minimal `FileChangeSet` (`relevant_files`: files named in the failure + package.json + src/main.ts, all files if no src/ file is named (playwright.config.ts only when named, M16), missing named files creatable; `check_fix`: only relevant/creatable paths, no delete, ≤ 3 files, ≤ max(20, 40 %) changed lines per file, no no-op updates, tests not removed/skipped, no raised timeouts/added waits in tests or config (M16), package.json rules; `fix`); graph node `fixer_node` reads `state.target_dir` read-only, no LLM call for passed/error results or exhausted `max_fix_attempts`, increments `fix_attempts`, sets `fix_changes` + `fixing`; empty proposal → error "no safe fix"; never writes | exists (M15) |
| reviewer | `agents/nodes/reviewer.py` | spec + project files + `TestResult` → `ReviewResult` (`review_facts`: build/tests outcome, hooks defined in src and used in tests, scene files outside `src/scenes/`, stray files — ground truth shown in the prompt; `files_summary`: tree + contents up to 16k chars, src first; `check_review`: exactly the 6 checks in order, approve ⇔ all checks passed and tests passed, build failed → `browser_game_suitable` false + reject, `test_hooks_present` = fact, layout facts → `files_organized` false, non-approve needs an issue, issues/notes may name a file outside the tree only to say it is missing; `review`); graph node `reviewer_node` reads `state.target_dir` read-only, sets `review_result`, keeps `status`; runs after the fix loop (passed / attempts used up); never writes | exists (M17) |
| human_gate | `agents/nodes/human_gate.py` | gated state → `needs_human_review` + `<target_dir>/.factory/state.json` (`human_gate_node`: needs `test_result` + `review_result`, saves via `save_state`, clears an old `human_decision`; errors start with `human_gate:`); `decide(state, decision, note)`: `needs_human_review` → `approved` / `rejected` / `needs_changes`, raises `GateError` otherwise or for approve with failed tests; `next_actions` / `format_gate`; `load_state` / `save_state`. Deterministic, no LLM; the last node of the fix-loop graph; decisions come from `scripts/decide.py` | exists (M18) |
