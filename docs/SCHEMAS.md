# Schemas reference

Pydantic v2 models in `agents/schemas/`, re-exported from `agents.schemas`. They are the contract between nodes: every LLM output must be parsed into one of these — free text is never a final result.

```python
from agents.schemas import GameSpec, TaskPlan, FileChange, GameFactoryState, FactoryStatus
from agents.schemas.examples import sample_game_spec   # Block Dodger samples for every model
```

## Common rules

- All models inherit `StrictModel` (`agents/schemas/game_spec.py`): `extra="forbid"` (unknown keys → `ValidationError`) and strings are whitespace-stripped — **except** `FileChange` and `CommandResult`, which keep whitespace exactly (file content, patches, command output). `FileChange.path` is trimmed explicitly.
- Parse LLM JSON with `Model.model_validate_json(text)`; describe the expected format to the LLM with `Model.model_json_schema()`.
- Sample data: `agents/schemas/examples.py` (`ALL_SAMPLES` maps model name → builder). Reuse it in scripts/tests instead of writing new fixtures.

## Models

| Model | File | Produced by | Consumed by |
|---|---|---|---|
| `GameIdea` | game_spec.py | user | planner (M4) |
| `GameSpec` (+ `Scene`, `Control`) | game_spec.py | planner (M4) | decomposer (M5), test writer (M11), reviewer (M17) |
| `ImplementationTask`, `TaskPlan` | task_plan.py | decomposer (M5) | coder (M8) |
| `FileChange` | task_plan.py | coder (M8), test writer (M11), fixer (M15) | applier (M9) |
| `FileChangeSet` | task_plan.py | coder (M8), test writer (M11), fixer (M15) — the `{"changes": [...]}` output | applier (M9) |
| `CommandResult` | test_result.py | safe command tools (M6), test runner (M12) | fixer, reviewer |
| `TestResult` (+ `TestFailure`) | test_result.py | test runner (M12) | fixer (M15), reviewer (M17) |
| `ReviewResult` (+ `ReviewCheck`) | review_result.py | reviewer (M17) | human approval (M18) |
| `HumanDecision` | agent_state.py | `decide` / `scripts/decide.py` (M18) | `next_actions`, saved state |
| `GameFactoryState`, `FactoryStatus` | agent_state.py | LangGraph graph (M7+) | all nodes |
| `NodeError` | node_error.py | any node on failure (M4+) | runners, graph (`state.error`) |

## Fields and invariants

**GameIdea** — `text` 3–500 chars.

**GameSpec** — `title`, `slug` (kebab-case `^[a-z0-9]+(-[a-z0-9]+)*$`), `genre`, `engine` (only `"phaser"`, default), `core_loop`, `scenes: [Scene(name, purpose)]` ≥1, `controls: [Control(input, action)]` ≥1, `win_condition`, `lose_condition`, `test_requirements: [str]` ≥1, `asset_requirements`, `sound_requirements` (default `[]`), `quality_requirements` (filled by code, M21b), `playtest` (M21c, written by the planner, checked by code: `player` (null | `{moves_by_itself}`), `inputs` [{input: key name or "Click", expect: player_left/right/up/down | score_up | state_changes}], `moves_on_its_own`, `hud` (time | input | none), `difficulty_ramps`, `round_end` ({by: timer, seconds} | {by: hook})). See `agents/generators/playtest.py`.

**ImplementationTask** — `id` (e.g. `T1`), `title`, `description`, `kind` ∈ `setup | config | code | test_hooks | tests | build | run_tests`, `target_files`, `depends_on` (task ids), `acceptance`.

**TaskPlan** — `game_slug` (same slug rule), `tasks` ≥1.
- task ids are unique;
- `depends_on` may reference **only earlier tasks** → list order is a valid execution order, no cycles.

**FileChange** — `path`, `operation` ∈ `create | update | delete`, `content`, `patch`, `reason`.
- `path` is relative to the target project: no leading `/`, `~`, `\`, no `:` (drive letters/URLs), no `..` segments. This is only a sanity check — the real path guard is in `agents/tools` (M6/M9).
- `create`/`update`: exactly one of `content` / `patch`. `delete`: neither.

**FileChangeSet** — `changes: [FileChange]` (default empty). Output wrapper of all file-proposing nodes; an empty set means "nothing to change" (e.g. coder on a build task).

**CommandResult** — `command`, `cwd`, `exit_code`, `stdout`, `stderr`, `duration_s ≥ 0`, `timed_out`; property `ok` = exit 0 and not timed out.

**TestResult** — `status` ∈ `passed | failed | error`, `command_results`, `failures: [TestFailure(name, message)]`, `summary`. `passed` ⇒ `failures` empty. Meaning (M12): `passed` = every step ran ok; `failed` = a step exited non-zero (build error, failing test, bad dependency) → **fixable**, goes to the fixer; `error` = could not run (missing project, SafetyError, timeout) → stop. Failure names: the command (`npm run build`) or `file › suite › test title`.

**ReviewResult** — `verdict` ∈ `approve | needs_changes | reject`, `checks: [ReviewCheck(name, passed, note)]`, `issues`, `suggestions`, `summary` (required).

**HumanDecision** (M18) — `decision` ∈ `approve | reject | needs_changes`, `note` (default `""`), `decided_at` (ISO 8601 UTC, required).

**GameFactoryState** — `user_idea` (required), `game_spec?`, `task_plan?`, `proposed_changes: [FileChange]` (coder, M13), `proposed_test_changes: [FileChange]` (test writer, M13), `template?` (template below `templates/` the project starts from, M19; `None` = from scratch; the graph's `run()` sets `phaser-vite-template`), `target_dir?` (project-relative apply target, M14), `changed_files` (written by the applier, M14), `fix_changes: [FileChange]` (latest fixer proposal, M15; cleared by apply_fix), `command_results`, `test_result?`, `review_result?`, `human_decision?` (M18), `loop_history: [LoopStep]` (fix loop, M16), `fix_attempts ≥ 0` (default 0), `max_fix_attempts` (default 5), `status: FactoryStatus` (default `new`), `error?`.

**LoopStep** (M16, agent_state.py) — one fix-loop step recorded by the graph: `step` ∈ `test | fix | apply_fix`, `attempt ≥ 0` (0 = first test run), `status` (test: `passed/failed/error`; fix: `proposed/error`; apply_fix: `applied/error`), `summary`, `files` (proposed / written paths, relative to the project).

**NodeError** — `node`, `message`, `attempts` (LLM calls made), `validation_errors: [str]` (`field.path: msg`), `raw_output?` (last LLM output). Nodes return it instead of raising; in the graph it is stored as `state.error = "<node>: <NodeError JSON>"` with `status=error`.

**FactoryStatus** (StrEnum): `new → planned → tasks_planned → coding → changes_proposed (dry run done, M13) → changes_applied (`--apply`, M14) → testing → tests_failed ⇄ fixing → tests_passed → needs_human_review → approved | rejected | needs_changes`; `error` from any step. Since M18 the fix loop ends at `needs_human_review` (also when attempts are used up — `test_result.status` tells which); the three decisions are set only by `decide` (M18).

## LangGraph usage

`GameFactoryState` works directly as a `StateGraph` schema (covered by `tests/test_schemas.py::StateTest.test_works_as_langgraph_state`):

```python
graph = StateGraph(GameFactoryState)
def planner(state: GameFactoryState) -> dict:          # nodes receive the model,
    return {"game_spec": spec, "status": FactoryStatus.PLANNED}   # return partial updates
```

`graph.compile().invoke({...})` returns a plain dict of field values; rebuild with `GameFactoryState.model_validate(...)` when a model is needed.

## Changing a schema

1. Edit the model, then update `examples.py`, this file, and `tests/test_schemas.py`.
2. Run `python scripts/validate_schemas.py` and the full test suite.
