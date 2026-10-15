"""Human approval gate (M18): stop the graph for a human decision, record it later.

Deterministic, no LLM. `human_gate_node` runs after the reviewer: it sets status
`needs_human_review`, saves the state to `<target_dir>/.factory/state.json` and the graph ends.
A human then decides with `scripts/decide.py`, which loads the state, calls `decide` and saves it:

    needs_human_review --approve--> approved        (only when the tests passed)
                       --reject---> rejected
                       --changes--> needs_changes   (nothing runs automatically)

`next_actions` lists what can be done next for each of these statuses.
Reference: docs/NODES.md, docs/ARCHITECTURE.md (Graph section).
"""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from agents.nodes.applier import check_fix_target
from agents.schemas import FactoryStatus, GameFactoryState, HumanDecision, TestFailure, TestResult
from agents.tools.filesystem import read_file, write_file
from agents.tools.safety import PROJECT_ROOT, SafetyError

NODE = "human_gate"
STATE_FILE = ".factory/state.json"
DECISIONS = {
    "approve": FactoryStatus.APPROVED,
    "reject": FactoryStatus.REJECTED,
    "needs_changes": FactoryStatus.NEEDS_CHANGES,
}
GATE_STATUSES = (FactoryStatus.NEEDS_HUMAN_REVIEW, *DECISIONS.values())


class GateError(ValueError):
    """A decision that is not allowed (nothing pending, approve with failing tests, unknown decision)."""


def state_path(target_dir: str) -> str:
    return f"{target_dir.rstrip('/')}/{STATE_FILE}"


def save_state(state: GameFactoryState, root: Path = PROJECT_ROOT) -> str:
    """Write the state as JSON inside its project (safe tools). Returns the project-relative path."""
    path = state_path(check_fix_target(state.target_dir, root))
    write_file(path, state.model_dump_json(indent=2, exclude_none=True) + "\n", root)
    return path


def load_state(target_dir: str, root: Path = PROJECT_ROOT) -> GameFactoryState:
    """Read `<target_dir>/.factory/state.json`. Raises SafetyError (bad dir / no file) or ValueError (invalid)."""
    path = state_path(check_fix_target(target_dir, root))
    try:
        text = read_file(path, root)
    except SafetyError as exc:
        raise SafetyError(f"no saved state in {target_dir} ({exc}); run the fix loop first") from exc
    try:
        return GameFactoryState.model_validate_json(text)
    except ValidationError as exc:
        raise ValueError(f"{path} is not a valid GameFactoryState: {exc.errors()[0]['msg']}") from exc


def saved_spec_and_plan(target_dir: str, root: Path = PROJECT_ROOT):
    """(GameSpec, TaskPlan | None) the project was generated from (its saved state), or None (M21c: scripts
    working on an existing project must use ITS spec, not the Block Dodger sample)."""
    try:
        state = load_state(target_dir, root)
    except (SafetyError, ValueError):
        return None
    return (state.game_spec, state.task_plan) if state.game_spec is not None else None


def human_gate_node(state: GameFactoryState, root: Path = PROJECT_ROOT) -> dict:
    """LangGraph node: status -> needs_human_review, state saved to the project; the graph ends here."""
    def error(message: str) -> dict:
        return {"status": FactoryStatus.ERROR, "error": f"{NODE}: {message}"}

    if state.test_result is None or state.review_result is None:
        return error("state needs test_result and review_result; run the test runner and the reviewer first")
    gated = state.model_copy(update={"status": FactoryStatus.NEEDS_HUMAN_REVIEW, "error": None,
                                     "human_decision": None})
    try:
        save_state(gated, root)
    except (SafetyError, OSError) as exc:
        return error(f"cannot save state: {exc}")
    return {"status": FactoryStatus.NEEDS_HUMAN_REVIEW, "human_decision": None, "error": None}


def decide(state: GameFactoryState, decision: str, note: str = "", now: datetime | None = None) -> GameFactoryState:
    """Apply a human decision to a gated state. Raises GateError when it is not allowed."""
    if decision not in DECISIONS:
        raise GateError(f"unknown decision {decision!r}; expected one of {list(DECISIONS)}")
    if state.status != FactoryStatus.NEEDS_HUMAN_REVIEW:
        raise GateError(f"no decision pending: status is {state.status.value}"
                        + (f" (decided: {state.human_decision.decision})" if state.human_decision else ""))
    if decision == "approve" and (state.test_result is None or state.test_result.status != "passed"):
        status = state.test_result.status if state.test_result else "not run"
        raise GateError(f"cannot approve: tests did not pass ({status}); use reject or changes")
    record = HumanDecision(decision=decision, note=note,
                           decided_at=(now or datetime.now(UTC)).isoformat(timespec="seconds"))
    return state.model_copy(update={"status": DECISIONS[decision], "human_decision": record})


HUMAN_REVIEW = "human review (decide.py changes)"


def human_review_failure(note: str) -> TestResult:
    """A human's "changes" note as a failing result, so the fixer implements it (M22)."""
    message = (f"A human played the game and asked for: {note}\n"
               "Implement exactly this in the game code (src/); keep everything else and all tests working.")
    return TestResult(status="failed", summary="human review: changes requested",
                      failures=[TestFailure(name=HUMAN_REVIEW, message=message)])


def next_actions(state: GameFactoryState) -> list[str]:
    """What a human can do next, for the current status."""
    target = state.target_dir or "<project>"
    decide_cmd = f"python scripts/decide.py --project-dir {target}"
    note = state.human_decision.note if state.human_decision else ""
    status = state.status
    if status == FactoryStatus.NEEDS_HUMAN_REVIEW:
        tests_passed = state.test_result is not None and state.test_result.status == "passed"
        actions = [f"play it: cd {target} && npm run dev"]
        if tests_passed:
            actions.append(f'approve: {decide_cmd} approve [--note "…"]')
        else:
            actions.append("approve is not available: the tests did not pass")
        return [*actions,
                f'request changes: {decide_cmd} changes --note "what to change"',
                f'reject: {decide_cmd} reject [--note "why"]']
    if status == FactoryStatus.APPROVED:
        return [f"build the artifact: cd {target} && npm run build   -> {target}/dist/",
                f"play the build: cd {target} && npx vite preview",
                "publishing is not automated"]
    if status == FactoryStatus.NEEDS_CHANGES:
        return [*([f"requested: {note}"] if note else []),
                f"let the fixer implement the note (then test, review, gate again): "
                f"python scripts/run_fix_loop.py --project-dir {target} --from-decision",
                f"or re-run only the tests and the fix loop: python scripts/run_fix_loop.py --project-dir {target}"]
    if status == FactoryStatus.REJECTED:
        return [f"the project stays in {target}/; delete it by hand if it is not needed",
                'or generate a new project: python agents/game_factory_graph.py "<idea>" --fix-loop']
    return [f"no human decision for status {status.value}"]


def format_gate(state: GameFactoryState) -> list[str]:
    """=== HUMAN REVIEW === body: status, reviewer verdict, decision, next actions."""
    lines = [f"status: {state.status.value}"]
    if state.test_result is not None:
        lines.append(f"tests: {state.test_result.status} ({state.test_result.summary})")
    if state.review_result is not None:
        lines.append(f"reviewer verdict: {state.review_result.verdict}")
    if state.human_decision:
        d = state.human_decision
        lines.append(f"human decision: {d.decision} at {d.decided_at}" + (f" · note: {d.note}" if d.note else ""))
    if state.target_dir and state.status in GATE_STATUSES:
        lines.append(f"saved state: {state_path(state.target_dir)}")
    return [*lines, "next actions:", *(f"  - {a}" for a in next_actions(state))]
