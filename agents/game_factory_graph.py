"""Game factory LangGraph workflow — dry run (M13), approved apply (M14), fix loop (M16), review (M17),
human gate (M18):

    START -> planner -> task_decomposer -> coder_dry_run -> test_writer_dry_run -> END
                                                                     └─> apply_changes -> END   (--apply)
                                                                     └─> apply_changes -> test_runner ─┬─> reviewer -> human_gate -> END   (--fix-loop)
                                                                              ▲                        │   passed / attempts used up
                                                                              └── apply_fix <- fixer <─┘ failed, attempts left

Every project starts from templates/phaser-vite-template (M19): the coder and test writer
update its files, the applier writes template + proposals; its config files are locked.
Without --apply: proposes a complete game project (code + tests) and writes nothing.
With --apply: additionally writes the final project into a new folder below generated/
or games/ (default generated/<slug>; never overwrites). After every node, status `error`
ends the graph (proposals made so far are kept in the state).
With --fix-loop (implies --apply): then runs install/build/Playwright; while tests fail and
fix attempts are left (--max-fix-attempts, default 5), the fixer proposes a minimal fix,
apply_fix writes it inside the project and the tests run again. A fix attempt that yields
nothing usable (fixer NodeError / no safe fix / apply_fix rejection) costs the attempt and the
fixer tries again (M20). When tests pass or the
attempts are used up, the reviewer returns a ReviewResult and the human gate stops the graph:
status `needs_human_review`, state saved to <target>/.factory/state.json; a human decides
later with scripts/decide.py (approve / reject / changes). An error from the test run or the
reviewer ends the graph without the gate. `build_fix_loop_graph` runs the same loop + review +
gate on an already written project (scripts/run_fix_loop.py).

Usage (from project root, Ollama running):
    python agents/game_factory_graph.py                       # Block Dodger idea, dry run
    python agents/game_factory_graph.py "game idea"           # any idea
    python agents/game_factory_graph.py "game idea" --show-files
    python agents/game_factory_graph.py "game idea" --json
    python agents/game_factory_graph.py "game idea" --apply [--target-dir generated/x]
    python agents/game_factory_graph.py "game idea" --fix-loop [--max-fix-attempts 5] [--target-dir generated/x]

Prints a filesystem proof: dry run — nothing changed; apply / fix loop — every changed file
is inside the target folder. Exit code 0 on success (`changes_proposed` / `changes_applied` /
`needs_human_review` with passing tests + proof), 2 when the apply target is refused, 1 otherwise.
Reference: docs/ARCHITECTURE.md (Graph section).
"""

import argparse
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.graph import END, START, StateGraph  # noqa: E402

from agents.generators.phaser_template import DEFAULT_TEMPLATE  # noqa: E402
from agents.llm import make_llm, model_name  # noqa: E402
from agents.run_log import LOG_DIR, RunLog, Timer, active, new_run_id, run_dir  # noqa: E402
from agents.nodes.applier import (  # noqa: E402
    TARGET_REFUSED,
    apply_fix_node,
    apply_node,
    check_target,
    default_target,
    write_manifest,
)
from agents.nodes.coder import coder_dry_run_node  # noqa: E402
from agents.nodes.fixer import failure_signature, fixer_node  # noqa: E402
from agents.nodes.human_gate import GATE_STATUSES, format_gate, human_gate_node  # noqa: E402
from agents.nodes.planner import planner_node  # noqa: E402
from agents.nodes.reviewer import ACCEPTANCE_ORDER, QUALITY_FAILURE, TESTS_COUNT, reviewer_node  # noqa: E402
from agents.nodes.task_decomposer import task_decomposer_node  # noqa: E402
from agents.nodes.test_runner import test_runner_node  # noqa: E402
from agents.nodes.test_writer import test_writer_dry_run_node  # noqa: E402
from agents.schemas import FactoryStatus, FileChange, GameFactoryState, LoopStep, TestResult  # noqa: E402
from agents.schemas.examples import BLOCK_DODGER_IDEA  # noqa: E402
from agents.tools.apply_changes import apply_changes  # noqa: E402
from agents.tools.filesystem import PROJECT_SKIP, file_hashes, read_file  # noqa: E402
from agents.tools.safety import PROJECT_ROOT, SafetyError  # noqa: E402


NODES = ("planner", "task_decomposer", "coder_dry_run", "test_writer_dry_run")
APPLY_NODES = (*NODES, "apply_changes")
LOOP_NODES = ("test_runner", "fixer", "apply_fix")
REVIEW_NODES = ("reviewer",)
GATE_NODES = ("human_gate",)
STEP_SUMMARY_CHARS = 200
MAX_FIX_ATTEMPTS_LIMIT = 20


def _next_or_end(next_node: str):
    def route(state: GameFactoryState) -> str:
        return END if state.status == FactoryStatus.ERROR else next_node
    return route


def _record(state: GameFactoryState, update: dict, step: LoopStep) -> dict:
    return {**update, "loop_history": [*state.loop_history, step]}


def _short(text: str | None, limit: int = STEP_SUMMARY_CHARS) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def acceptance_stage(result: TestResult) -> int:
    """How far the acceptance test got (M21b): its steps run in ACCEPTANCE_ORDER and stop at the first
    failure. len(ACCEPTANCE_ORDER) = passed (or no acceptance failure); index of the failed [step];
    -1 = it failed without a step tag (TypeError, timeout: worse than any tagged step); -2 = no tests ran."""
    if result.status == "passed":
        return len(ACCEPTANCE_ORDER)
    if not TESTS_COUNT.search(result.summary):
        return -2
    failures = [f for f in result.failures if "acceptance.spec.ts" in f.name]
    if not failures:
        return len(ACCEPTANCE_ORDER)
    tags = [tag for tag, _ in QUALITY_FAILURE.findall(failures[0].message)]
    return ACCEPTANCE_ORDER.index(tags[0]) if tags else -1


def test_rank(result: TestResult) -> tuple[int, int, int]:
    """(build ok, acceptance progress, tests passed) for comparing two runs of the same project; higher is
    better (M21b). Progress comes before the count: a fix that gets the acceptance test further is kept
    even when another test now fails (r12 fix #2: [controls] -> [hud_visible], 3/6 -> 2/6)."""
    count = TESTS_COUNT.search(result.summary)
    return (int(result.status == "passed" or "build ok" in result.summary), acceptance_stage(result),
            int(count.group(1)) if count else -1)


def made_worse(result: TestResult, baseline: TestResult) -> bool:
    """The run after a fix is worse than the run before it: the build broke or fewer tests pass."""
    return result.status != "passed" and test_rank(result) < test_rank(baseline)


def _test_step(state: GameFactoryState, root: Path) -> dict:
    update = test_runner_node(state, root=root)
    result = update["test_result"]
    records = state.fix_records
    if (records and records[-1].attempt == state.fix_attempts and result.status == "failed"
            and failure_signature(result) == records[-1].signature):  # the last fix changed nothing (M21)
        update = {**update, "fix_records": [*records[:-1], records[-1].model_copy(update={"no_effect": True})]}
    update = {**update, "fix_backup": [], "fix_baseline": None}
    test = LoopStep(step="test", attempt=state.fix_attempts, status=result.status, summary=result.summary)
    baseline = state.fix_baseline
    if not (state.fix_backup and baseline and update.get("status") != FactoryStatus.ERROR
            and made_worse(result, baseline)):
        return _record(state, update, test)
    # M21b: the last fix made things worse -> put the files back, keep testing from the baseline
    files = [c.path for c in state.fix_backup]
    reverted = apply_changes(state.fix_backup, state.target_dir, apply=True, root=root)
    if not reverted.ok:
        step = LoopStep(step="revert", attempt=state.fix_attempts, status="error", files=files,
                        summary=_short(f"could not revert: {reverted.summary()}"))
        return {**update, "loop_history": [*state.loop_history, test, step]}
    write_manifest(state.target_dir, "revert", root)
    records = update.get("fix_records", records)
    if records and records[-1].attempt == state.fix_attempts:  # no line blocking: an exact repeat stays refused
        records = [*records[:-1], records[-1].model_copy(update={"no_effect": False, "made_worse": True})]
    first = f" (first failure: {result.failures[0].name}: {result.failures[0].message})" if result.failures else ""
    step = LoopStep(step="revert", attempt=state.fix_attempts, status="reverted", files=files,
                    summary=_short(f"{result.summary}{first} is worse than before the fix ({baseline.summary}); "
                                   "the fix was undone", 400))
    return {**update, "test_result": baseline, "status": FactoryStatus.TESTS_FAILED, "fix_records": records,
            "loop_history": [*state.loop_history, test, step]}


def _fix_backup(state: GameFactoryState, root: Path) -> list[FileChange]:
    """Changes that undo `state.fix_changes`: the old content of each file, or a delete for a new one.

    [] (no revert possible) when an existing file cannot be read: never turn it into a delete.
    """
    backup = []
    for change in state.fix_changes:
        reason = f"revert fix attempt {state.fix_attempts}"
        path = f"{state.target_dir}/{change.path}"
        if not (Path(root) / path).exists():
            if change.operation != "delete":
                backup.append(FileChange(path=change.path, operation="delete", reason=reason))
            continue
        try:
            backup.append(FileChange(path=change.path, operation="update", content=read_file(path, root),
                                     reason=reason))
        except (SafetyError, OSError, ValueError):
            return []
    return backup


def _failed_attempt(update: dict) -> dict:
    """A fix attempt that produced nothing usable costs the attempt but does not end the loop (M20)."""
    return {**update, "status": FactoryStatus.TESTS_FAILED, "error": None, "fix_changes": []}


def _fix_step(state: GameFactoryState, llm, root: Path) -> dict:
    update = fixer_node(state, llm=llm, root=root)
    attempt = update.get("fix_attempts", state.fix_attempts)
    if update["status"] == FactoryStatus.ERROR:
        step = LoopStep(step="fix", attempt=attempt, status="error", summary=_short(update["error"]))
        if "fix_attempts" in update:  # the model failed this attempt; precondition errors stay fatal
            update = _failed_attempt(update)
    else:
        changes = update["fix_changes"]
        step = LoopStep(step="fix", attempt=attempt, status="proposed", files=[c.path for c in changes],
                        summary=_short(" | ".join(c.reason for c in changes)))
    return _record(state, update, step)


def _apply_fix_step(state: GameFactoryState, root: Path) -> dict:
    backup = _fix_backup(state, root) if state.target_dir else []
    update = apply_fix_node(state, root=root)
    if update["status"] != FactoryStatus.ERROR:  # M21b: remember how to undo it and what it is measured against
        update = {**update, "fix_backup": backup, "fix_baseline": state.test_result}
    if update["status"] == FactoryStatus.ERROR:
        step = LoopStep(step="apply_fix", attempt=state.fix_attempts, status="error", summary=_short(update["error"]))
        update = _failed_attempt(update)  # all-or-nothing: nothing was written
    else:
        step = LoopStep(step="apply_fix", attempt=state.fix_attempts, status="applied",
                        files=[c.path for c in state.fix_changes])
    return _record(state, update, step)


def _after_test(state: GameFactoryState) -> str:
    """Failed tests with attempts left -> fixer; passed or exhausted -> reviewer; error -> END."""
    if state.status == FactoryStatus.TESTS_FAILED and state.fix_attempts < state.max_fix_attempts:
        return "fixer"
    if state.status in (FactoryStatus.TESTS_PASSED, FactoryStatus.TESTS_FAILED):
        return "reviewer"
    return END


def _after_fix_attempt(state: GameFactoryState) -> str:
    """After fixer / apply_fix: proposal -> apply_fix; applied -> test_runner; failed attempt -> retry or review."""
    if state.status == FactoryStatus.ERROR:
        return END
    if state.status == FactoryStatus.FIXING:
        return "apply_fix"
    if state.status == FactoryStatus.TESTING:
        return "test_runner"
    return "fixer" if state.fix_attempts < state.max_fix_attempts else "reviewer"


def _add_fix_loop(graph: StateGraph, llm, root: Path) -> None:
    """test_runner -> (fixer -> apply_fix -> test_runner)* -> reviewer -> human_gate ; entry edge is the caller's."""
    graph.add_node("test_runner", lambda state: _test_step(state, root))
    graph.add_node("fixer", lambda state: _fix_step(state, llm, root))
    graph.add_node("apply_fix", lambda state: _apply_fix_step(state, root))
    graph.add_node("reviewer", lambda state: reviewer_node(state, llm=llm, root=root))
    graph.add_conditional_edges("test_runner", _after_test, {"fixer": "fixer", "reviewer": "reviewer", END: END})
    graph.add_node("human_gate", lambda state: human_gate_node(state, root=root))
    graph.add_conditional_edges("reviewer", _next_or_end("human_gate"), {"human_gate": "human_gate", END: END})
    graph.add_edge("human_gate", END)
    targets = {"apply_fix": "apply_fix", "test_runner": "test_runner", "fixer": "fixer", "reviewer": "reviewer", END: END}
    graph.add_conditional_edges("fixer", _after_fix_attempt, targets)
    graph.add_conditional_edges("apply_fix", _after_fix_attempt, targets)


def recursion_limit(max_fix_attempts: int, prefix_nodes: int = len(APPLY_NODES)) -> int:
    """LangGraph step budget: prefix + first test + 3 steps per fix attempt + review + gate, plus slack."""
    return prefix_nodes + 1 + len(LOOP_NODES) * max_fix_attempts + len(REVIEW_NODES) + len(GATE_NODES) + 5


def build_graph(llm=None, apply: bool = False, root: Path = PROJECT_ROOT, fix_loop: bool = False):
    """Compile the graph. All LLM nodes share `llm` (default: make_llm() inside each node).

    `apply=True` adds the apply_changes node, which writes below `root` (tests use a temp root).
    `fix_loop=True` (implies apply) continues with test_runner and the fixer loop.
    """
    apply = apply or fix_loop
    nodes = APPLY_NODES if apply else NODES
    graph = StateGraph(GameFactoryState)
    graph.add_node("planner", lambda state: planner_node(state, llm=llm))
    graph.add_node("task_decomposer", lambda state: task_decomposer_node(state, llm=llm))
    graph.add_node("coder_dry_run", lambda state: coder_dry_run_node(state, llm=llm))
    graph.add_node("test_writer_dry_run", lambda state: test_writer_dry_run_node(state, llm=llm))
    if apply:
        graph.add_node("apply_changes", lambda state: apply_node(state, root=root))
    graph.add_edge(START, nodes[0])
    for current, following in zip(nodes, nodes[1:]):
        graph.add_conditional_edges(current, _next_or_end(following), {following: following, END: END})
    if fix_loop:
        _add_fix_loop(graph, llm, root)
        graph.add_conditional_edges(nodes[-1], _next_or_end("test_runner"), {"test_runner": "test_runner", END: END})
    else:
        graph.add_edge(nodes[-1], END)
    return graph.compile()


def build_fix_loop_graph(llm=None, root: Path = PROJECT_ROOT, start: str = "test_runner"):
    """START -> test_runner -> fix loop -> reviewer -> human_gate, for an already written project (state.target_dir).

    `start="fixer"` (M22) begins with a fix for `state.test_result`, e.g. a human's "changes" note.
    """
    graph = StateGraph(GameFactoryState)
    _add_fix_loop(graph, llm, root)
    graph.add_edge(START, start)
    return graph.compile()


def _to_state(out: dict) -> GameFactoryState:
    return GameFactoryState.model_validate(
        {k: v.model_dump() if hasattr(v, "model_dump") else v for k, v in out.items()}
    )


def _clip(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize_update(update: dict, state: dict) -> str:
    """Short run-log line for what one node changed (M21b); `state` is the merged state after it."""
    get = lambda v, k, d=None: getattr(v, k, None) if not isinstance(v, dict) else v.get(k, d)  # noqa: E731
    parts = []
    if (spec := update.get("game_spec")) is not None:
        parts.append(f'spec "{get(spec, "title")}" ({len(get(spec, "scenes") or [])} scenes, '
                     f'{len(get(spec, "controls") or [])} controls, {len(get(spec, "quality_requirements") or [])} quality req)')
    if (plan := update.get("task_plan")) is not None:
        tasks = get(plan, "tasks") or []
        parts.append(f"{len(tasks)} tasks: " + ", ".join(f"{get(t, 'id')} {get(t, 'title')}" for t in tasks))
    for key, label in (("proposed_changes", "code"), ("proposed_test_changes", "tests"), ("fix_changes", "fix")):
        if update.get(key):
            paths = [get(c, "path") for c in update[key]]
            parts.append(f"{label}: {len(paths)} files ({', '.join(paths)})")
    if update.get("changed_files"):
        parts.append(f"wrote {len(update['changed_files'])} files")
    history = update.get("loop_history") or []
    reverted = bool(history) and get(history[-1], "step") == "revert"
    if (result := update.get("test_result")) is not None and not reverted:  # after a revert: the baseline
        failures = get(result, "failures") or []
        first = f" · first failure: {get(failures[0], 'name')}: {get(failures[0], 'message')}" if failures else ""
        parts.append(f"{get(result, 'status')}: {get(result, 'summary')}{first}")
    if (review := update.get("review_result")) is not None:
        failed = [get(c, "name") for c in get(review, "checks") or [] if not get(c, "passed")]
        parts.append(f"verdict {get(review, 'verdict')}" + (f", failed checks: {', '.join(failed)}" if failed
                                                             else ", all checks passed"))
    if "fix_attempts" in update:
        parts.append(f"fix attempt {update['fix_attempts']}/{state.get('max_fix_attempts')}")
    if reverted:
        parts.append(f"REVERT ({get(history[-1], 'status')}): {get(history[-1], 'summary')}")
    status = update.get("status", state.get("status"))
    parts.append(f"→ {getattr(status, 'value', status)}")
    if update.get("error"):
        parts.append(f"error: {update['error']}")
    return _clip(" · ".join(str(p) for p in parts), 600)


def _invoke(graph, state: dict | GameFactoryState, config: dict, log: RunLog | None) -> GameFactoryState:
    """graph.invoke, or (with a run log) graph.stream with one `node` event per finished node."""
    if log is None:
        return _to_state(graph.invoke(state, config=config))
    merged, timer = dict(state), Timer()  # a GameFactoryState iterates as (field, value) pairs
    with active(log):
        for chunk in graph.stream(state, config=config, stream_mode="updates"):
            for node, update in chunk.items():
                update = update or {}
                merged.update(update)
                log.event("node", node=node, duration_s=round(timer.lap(), 1), summary=summarize_update(update, merged),
                          status=str(getattr(merged.get("status"), "value", merged.get("status"))))
    final = _to_state(merged)
    log.event("end", status=final.status.value, error=final.error, duration_s=round(timer.total(), 1),
              target_dir=final.target_dir)
    return final


def run(idea: str, llm=None, apply: bool = False, target_dir: str | None = None,
        root: Path = PROJECT_ROOT, fix_loop: bool = False, max_fix_attempts: int = 5,
        template: str | None = DEFAULT_TEMPLATE, log: RunLog | None = None) -> GameFactoryState:
    """`template=None` builds the project from scratch (pre-M19 behaviour). `log` (M21b): run log."""
    graph = build_graph(llm, apply=apply, root=root, fix_loop=fix_loop)
    return _invoke(graph, {"user_idea": idea, "target_dir": target_dir, "max_fix_attempts": max_fix_attempts,
                           "template": template},
                   {"recursion_limit": recursion_limit(max_fix_attempts)}, log)


def run_fix_loop(state: GameFactoryState, llm=None, root: Path = PROJECT_ROOT,
                 start: str = "test_runner", log: RunLog | None = None) -> GameFactoryState:
    """Run test_runner + fix loop + review + gate on `state.target_dir` (needs game_spec; task_plan optional)."""
    graph = build_fix_loop_graph(llm, root=root, start=start)
    return _invoke(graph, state, {"recursion_limit": recursion_limit(state.max_fix_attempts, prefix_nodes=0)},
                   log)


def open_run_log(root: Path, run_id: str | None, label: str, model: str, what: str,
                 echo=None) -> RunLog:
    """Create logs/runs/<run_id>/ (default id: time + label) and log the `start` event."""
    run_id = run_id or new_run_id(label)
    log = RunLog(run_dir(root, run_id), echo=echo)
    log.event("start", run_id=run_id, model=model, what=what)
    return log


def _format_changes(changes, show_files: bool) -> list[str]:
    if not changes:
        return ["(none)"]
    lines = []
    width = max(len(c.path) for c in changes)
    for c in changes:
        body = c.content if c.content is not None else (c.patch or "")
        lines.append(f"{c.operation.upper():<7}{c.path:<{width}}  {len(body.splitlines()):>4} lines  {c.reason}")
    if show_files:
        for c in changes:
            body = c.content if c.content is not None else (c.patch or "")
            lines += ["", f"--- {c.path} ---", body.rstrip()]
    return lines


def format_loop(state: GameFactoryState) -> list[str]:
    """One line per loop step + the last failure messages + why the loop stopped (from test_result, not status)."""
    lines = []
    for s in state.loop_history:
        files = f"  [{', '.join(s.files)}]" if s.files else ""
        lines.append(f"#{s.attempt}  {s.step:<10}{s.status:<9}{s.summary}{files}")
    result = state.test_result
    if result is not None and result.status != "passed":
        for failure in result.failures[:3]:
            message = "\n      ".join(failure.message.strip().splitlines()[:4])
            lines.append(f"    last failure: {failure.name}: {message}")
    if result is None or result.status == "error" or state.status == FactoryStatus.ERROR:
        verdict = f"stopped: error after {state.fix_attempts} fix attempt(s)"
    elif result.status == "passed":
        verdict = f"tests passed after {state.fix_attempts} fix attempt(s)"
    else:
        verdict = f"stopped: fix attempts exhausted ({state.fix_attempts}/{state.max_fix_attempts}), tests still fail"
    return [*lines, verdict]


def format_review(review) -> list[str]:
    """Verdict, one line per check, issues and suggestions."""
    lines = [f"verdict: {review.verdict}", review.summary]
    lines += [f"  {'PASS' if c.passed else 'FAIL'}  {c.name:<22}{c.note}" for c in review.checks]
    lines += [f"  issue: {i}" for i in review.issues]
    lines += [f"  suggestion: {s}" for s in review.suggestions]
    return lines


def format_state(state: GameFactoryState, show_files: bool = False) -> str:
    lines = []
    spec = state.game_spec
    lines.append("=== GAME SPEC ===")
    if spec is None:
        lines.append("(none)")
    else:
        lines += [
            f"{spec.title} ({spec.slug}) · {spec.genre} · {spec.engine}",
            f"Core loop: {spec.core_loop}",
            "Scenes: " + ", ".join(s.name for s in spec.scenes),
            "Controls: " + "; ".join(f"{c.input} → {c.action}" for c in spec.controls),
            f"Win: {spec.win_condition}",
            f"Lose: {spec.lose_condition}",
            "Test requirements:",
            *(f"  - {r}" for r in spec.test_requirements),
        ]

    lines += ["", "=== TASK PLAN ==="]
    plan = state.task_plan
    if plan is None:
        lines.append("(none)")
    else:
        width = max(len(t.title) for t in plan.tasks)
        for t in plan.tasks:
            deps = ",".join(t.depends_on) or "-"
            files = ", ".join(t.target_files) or "-"
            lines.append(f"{t.id:<4}{t.kind:<11}{t.title:<{width}}  deps: {deps:<8} files: {files}")

    lines += ["", "=== PROPOSED FILES ===", *_format_changes(state.proposed_changes, show_files)]
    lines += ["", "=== PROPOSED TESTS ===", *_format_changes(state.proposed_test_changes, show_files)]
    if state.changed_files:
        lines += ["", f"=== APPLIED → {state.target_dir} ===", *(f"WROTE  {p}" for p in state.changed_files)]
    if state.loop_history:
        lines += ["", "=== FIX LOOP ===", *format_loop(state)]
    if state.review_result:
        lines += ["", "=== REVIEW ===", *format_review(state.review_result)]
    if state.status in GATE_STATUSES:
        lines += ["", "=== HUMAN REVIEW ===", *format_gate(state)]
    lines += ["", "=== STATUS ===", state.status.value]
    if state.error:
        lines.append(f"error: {state.error}")
    return "\n".join(lines)


def gate_passed(state: GameFactoryState) -> bool:
    """Fix loop success: stopped at the human gate with passing tests."""
    return (state.status == FactoryStatus.NEEDS_HUMAN_REVIEW
            and state.test_result is not None and state.test_result.status == "passed")


def project_hashes(root: Path) -> dict[str, str]:
    """file_hashes(root) without the run logs (M21b), which every logged run writes below logs/runs/."""
    return {path: digest for path, digest in file_hashes(root).items() if not path.startswith(f"{LOG_DIR}/")}


def _apply_proof(before: dict[str, str], after: dict[str, str], target: str | None) -> tuple[list[str], list[str]]:
    """Paths created/changed/removed between two snapshots: (inside target, outside target)."""
    diff = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    prefix = f"{target}/" if target else None
    inside = [p for p in diff if prefix and p.startswith(prefix)]
    return inside, [p for p in diff if p not in inside]


def main(argv: list[str], llm=None, root: Path = PROJECT_ROOT) -> int:
    parser = argparse.ArgumentParser(description="Idea -> spec -> plan -> proposed code + tests (dry run, or --apply)")
    parser.add_argument("idea", nargs="?", default=BLOCK_DODGER_IDEA)
    parser.add_argument("--json", action="store_true", help="print the full GameFactoryState as JSON")
    parser.add_argument("--show-files", action="store_true", help="print the content of every proposed file")
    parser.add_argument("--apply", action="store_true",
                        help="write the proposed project into a new folder below generated/ or games/")
    parser.add_argument("--fix-loop", action="store_true",
                        help="--apply, then test and fix in a loop until tests pass or attempts run out")
    parser.add_argument("--max-fix-attempts", type=int, help="fix loop budget (default 5); requires --fix-loop")
    parser.add_argument("--target-dir", help="apply target (default generated/<slug>); requires --apply")
    parser.add_argument("--model", help="Ollama model for every LLM node (default: $GAME_FACTORY_MODEL, "
                                        f"else .env; now {model_name()})")
    parser.add_argument("--run-id", help=f"run log folder name below {LOG_DIR}/ (default: time + slug); "
                                         "a run with an injected test LLM is logged only with --run-id")
    args = parser.parse_args(argv[1:])
    args.apply = args.apply or args.fix_loop
    with_log = llm is None or args.run_id is not None
    if args.target_dir and not args.apply:
        parser.error("--target-dir requires --apply")
    if args.max_fix_attempts is not None and not args.fix_loop:
        parser.error("--max-fix-attempts requires --fix-loop")
    if args.max_fix_attempts is not None and not 0 <= args.max_fix_attempts <= MAX_FIX_ATTEMPTS_LIMIT:
        parser.error(f"--max-fix-attempts must be between 0 and {MAX_FIX_ATTEMPTS_LIMIT}")
    max_fix_attempts = 5 if args.max_fix_attempts is None else args.max_fix_attempts

    if args.target_dir:  # refuse a bad explicit target before spending minutes on LLM calls
        try:
            check_target(args.target_dir, root)
        except SafetyError as exc:
            print(f"error: {TARGET_REFUSED}: {exc}\nnothing was run or written")
            return 2

    if llm is None and args.model:
        llm = make_llm(args.model)
    if not args.json:
        print(f"model: {model_name(args.model)}" + (" (injected)" if llm is not None and not args.model else ""),
              flush=True)
    before = project_hashes(root)
    log = None
    if with_log:  # M21b: what the agents do, while they do it (stderr with --json: stdout stays JSON)
        echo = (lambda line: print(line, file=sys.stderr, flush=True)) if args.json else \
            (lambda line: print(line, flush=True))
        try:
            log = open_run_log(root, args.run_id, Path(args.target_dir).name if args.target_dir else "run",
                               model_name(args.model), args.idea, echo=echo)
        except ValueError as exc:
            print(f"error: {exc}")
            return 2
        echo(f"run log: {log.dir.relative_to(root)}/run.log (LLM calls: llm/; viewer: scripts/show_run.py)")
    state = run(args.idea, llm=llm, apply=args.apply, target_dir=args.target_dir, root=root,
                fix_loop=args.fix_loop, max_fix_attempts=max_fix_attempts, log=log)
    after = project_hashes(root)
    inside, outside = _apply_proof(before, after, state.target_dir if args.apply else None)
    if args.json:
        print(state.model_dump_json(indent=2, exclude_none=True))
    else:
        print(format_state(state, show_files=args.show_files))
        if not args.apply:
            print(f"\n=== DRY RUN ===\nfilesystem unchanged: {'yes' if not outside else 'NO'} "
                  f"({len(before)} project files hashed before/after)")
            if state.status == FactoryStatus.CHANGES_PROPOSED and state.game_spec:
                print(f"re-run with --apply to write the project to {default_target(state.game_spec.slug)}/")
        else:
            sources = [p for p in inside if not any(skip in p for skip in PROJECT_SKIP)]
            print(f"\n=== APPLY CHECK ===\nfiles changed inside {state.target_dir}/: {len(inside)}"
                  + (f" ({len(sources)} source files; the rest are test runner outputs and .factory/state.json)"
                     if args.fix_loop else "")
                  + f"\nfiles changed outside it: {len(outside)}" + "".join(f"\n  OUTSIDE  {p}" for p in outside))
    if outside:
        return 1
    if (state.error or "").startswith(f"applier: {TARGET_REFUSED}"):
        return 2
    if args.fix_loop:
        return 0 if gate_passed(state) else 1
    if args.apply:
        written = sorted(p for p in inside if "/.factory/" not in p)  # .factory/: manifest + gate state (M18/M21)
        return 0 if state.status == FactoryStatus.CHANGES_APPLIED and written == sorted(state.changed_files) else 1
    return 0 if state.status == FactoryStatus.CHANGES_PROPOSED else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
