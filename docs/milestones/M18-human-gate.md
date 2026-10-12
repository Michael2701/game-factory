# M18 — Human Approval Gate

Status: complete (2026-10-12)

## Scope

States `tests_passed`, `needs_human_review`, `approved`, `rejected`, `needs_changes`. After the review, the graph stops for a human and prints the possible next actions. A human decides later with a separate command.

## Done criteria

The graph reaches a human review state and stops. **Met:**
- the real two-bugs loop ends at `needs_human_review` with the state saved in the project;
- `decide.py` records a decision once and prints the next actions;
- nothing changed outside the project.

## Graph

```
… apply_changes → test_runner ─┬─ passed / attempts used up → reviewer → human_gate → END (needs_human_review)
                    ▲          ├─ error → END (no review)        reviewer error → END (no gate)
                    │          └─ failed, attempts left → fixer → apply_fix ─┐
                    └─────────────────────────────────────────────────────────┘
later, a human:  scripts/decide.py --project-dir <dir> approve | reject | changes [--note …]
                 needs_human_review → approved | rejected | needs_changes
```

## Design decisions

- **END + state file, not LangGraph `interrupt()`.** `interrupt()` needs a checkpointer that survives the process. Only the in-memory one is installed, and the human decides minutes or days later in another process. The gate therefore saves the full `GameFactoryState` to `<target_dir>/.factory/state.json` and the graph ends. The file is plain JSON inside the project, easy to inspect.
- **Exhausted attempts (`tests_failed`) also reach the gate**: the human decides what to do with a project that still fails. A test-runner or reviewer error does not.
- **Approve needs passing tests.** Otherwise only reject or changes are allowed (`GateError`, exit 2).
- **One decision per gate.** Deciding again is refused; re-running the fix loop on the project creates a new gate.
- **`needs_changes` triggers nothing automatically.** The next actions suggest re-running the fix loop or editing by hand. Feeding the note to the fixer is future work.

## Changes

- `agents/schemas/agent_state.py`:
  - new `HumanDecision` (decision, note, decided_at);
  - `GameFactoryState.human_decision`;
  - sample data in `examples.py` (validate_schemas: 10 models).
- `agents/nodes/human_gate.py` (new, deterministic):
  - `human_gate_node`: needs `test_result` and `review_result`; sets `needs_human_review`, clears an old decision and saves the state via the safe tools (`write_file`, existing project below `generated/`/`games/` only). Errors start with `human_gate:`.
  - `decide`: the 3 transitions plus the refusals above.
  - `next_actions` per status:
    - gate: `npm run dev` and the 3 decide commands; "approve is not available" when tests failed;
    - approved: `npm run build` → `dist/`;
    - needs_changes: the note, then re-run the fix loop or edit by hand;
    - rejected: the project stays on disk, or generate a new one.
  - `format_gate` prints the `=== HUMAN REVIEW ===` section.
  - `save_state` / `load_state`.
- `agents/tools/filesystem.py`: `.factory/` added to `PROJECT_SKIP`, so the fixer, reviewer, test writer and the source diff never see the state file.
- `agents/game_factory_graph.py`:
  - `reviewer → human_gate → END`, and a reviewer error goes to END;
  - `GATE_NODES`; `recursion_limit` +1;
  - `format_loop` takes the outcome from `test_result` (status is now `needs_human_review`);
  - `format_state` prints `=== HUMAN REVIEW ===`;
  - new `gate_passed(state)`: `needs_human_review` and tests passed. This is the `--fix-loop` exit 0 condition (it was `tests_passed`).
- `scripts/run_fix_loop.py`: prints HUMAN REVIEW; exit 0 = `gate_passed` and nothing changed outside.
- `scripts/decide.py` (new): `--project-dir` plus `approve | reject | changes [--note]` or `--show`.
  - Exit 0 on success.
  - Exit 1 when the state is missing or invalid.
  - Exit 2 on a usage error, a bad dir or a refused decision; nothing is written in these cases.
- Tests:
  - `tests/test_human_gate.py` (new, 23 tests);
  - `tests/test_fix_loop.py`: final status `needs_human_review` (outcome in `test_result`), gate node and edges, recursion limit, CLI and script output, no gate after an error, `.factory` not in the source diff.
- Docs: ARCHITECTURE, NODES, SCHEMAS, TOOLS, TESTING, ROADMAP, README, CLAUDE.md, this file.

## Real runs

`python scripts/run_fix_loop.py --case two-bugs --target-dir generated/fix-demo-two-bugs-m18` (exit 0, 77 s): 2 fix rounds, then tests passed 3/3. The review says `needs_changes`, which is correct for the stub fixture (no movement, no win/lose feedback, no restart).

```
=== HUMAN REVIEW ===
status: needs_human_review
tests: passed (install ok · build ok · tests 3/3 passed)
reviewer verdict: needs_changes
saved state: generated/fix-demo-two-bugs-m18/.factory/state.json
next actions:
  - play it: cd generated/fix-demo-two-bugs-m18 && npm run dev
  - approve: python scripts/decide.py --project-dir generated/fix-demo-two-bugs-m18 approve [--note "…"]
  - request changes: python scripts/decide.py --project-dir generated/fix-demo-two-bugs-m18 changes --note "what to change"
  - reject: python scripts/decide.py --project-dir generated/fix-demo-two-bugs-m18 reject [--note "why"]
…
files changed inside generated/fix-demo-two-bugs-m18/: 11 (8 source files; the rest are test runner outputs and .factory/state.json)
files changed outside it: 0
```

Then `decide.py`:
- `changes --note "add left/right controls, win/lose message and a restart key"` → exit 0; status `needs_changes`, the decision is recorded with a timestamp, and the next actions are printed.
- `approve` afterwards → exit 2: `no decision pending: status is needs_changes (decided: needs_changes)`, nothing written.
- `--show` → exit 0, same section.
- `--project-dir generated/block-dodger --show` → exit 1: `no saved state … run the fix loop first`.

## Verification log

| Check | Result |
|---|---|
| fast suite | 356 tests OK (16 skipped gated), 6.1 s |
| full gated suite (`RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1`) | **356 tests OK, 0 skipped**, 564 s: real two-bugs loop now ends at the gate (`status: needs_human_review`), real reviewer tests, real fixtures, M13 e2e |
| validate_schemas / smoke_graph | ok (10 models) / exit 0, sha256 = baseline `e0ff1d10…` |

## Findings / issues

- **The reviewer's verdict and the gate are independent.** The two-bugs project passes its tests, so `approve` is allowed even though the reviewer said `needs_changes`. The human sees both and decides. Making `approve` depend on the reviewer would put the human under the model.
- **The note from `needs_changes` goes nowhere yet.** `run_fix_loop.py --project-dir` only fixes failing tests; it does not implement requested features. Turning human notes into tasks for the coder belongs to a later milestone (M19/M20 or after).
- **Re-running the loop replaces the state file.** The old decision is overwritten. Keeping a history of gates is not needed yet.
- `generated/fix-demo-two-bugs-m18` is kept as a run output; its `.factory/state.json` holds the `needs_changes` decision.
