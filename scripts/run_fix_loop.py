"""Run the fix loop (M16) on a deliberately broken project or an existing generated project.

Usage (from project root, Ollama running, network for npm install):
    python scripts/run_fix_loop.py                                    # case phaser-default -> generated/fix-demo-phaser-default
    python scripts/run_fix_loop.py --case two-bugs                    # needs two loop rounds
    python scripts/run_fix_loop.py --case import-case --target-dir generated/x
    python scripts/run_fix_loop.py --project-dir generated/block-dodger   # loop on an existing project
    python scripts/run_fix_loop.py --max-fix-attempts 3 --json

--case writes the broken fixture (agents/fixtures/broken_projects.py) into a NEW folder
(never overwrites; exit 2 if it exists and is not empty), then runs
test_runner -> fixer -> apply_fix -> test_runner ... until tests pass or the attempts run out,
then the reviewer (M17) returns a ReviewResult and the human gate (M18) stops the graph at
`needs_human_review` (state saved to <project>/.factory/state.json; decide with scripts/decide.py).
Prints every loop step, the source changes the loop made (unified diff) and a filesystem
proof (every changed file is inside the project; node_modules/dist/test reports are test
runner outputs). Context for the fixer: the sample Block Dodger GameSpec + TaskPlan.
Exit code 0 when the loop stops at the human gate with passing tests and nothing changed
outside the project; 1 otherwise;
2 on usage / refused target.
"""

import argparse
import difflib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.fixtures.broken_projects import CASES  # noqa: E402
from agents.game_factory_graph import (  # noqa: E402
    MAX_FIX_ATTEMPTS_LIMIT,
    _apply_proof,
    format_loop,
    format_review,
    gate_passed,
    open_run_log,
    project_hashes,
    run_fix_loop,
)
from agents.llm import make_llm, model_name  # noqa: E402
from agents.nodes.applier import check_fix_target, check_target  # noqa: E402
from agents.nodes.human_gate import (  # noqa: E402
    GATE_STATUSES,
    format_gate,
    human_review_failure,
    load_state,
    saved_spec_and_plan,
)
from agents.schemas import FactoryStatus, FileChange, GameFactoryState  # noqa: E402
from agents.schemas.examples import sample_game_spec, sample_task_plan  # noqa: E402
from agents.tools.apply_changes import apply_changes  # noqa: E402
from agents.tools.filesystem import PROJECT_SKIP, read_project  # noqa: E402
from agents.tools.safety import SafetyError  # noqa: E402


def default_case_target(case: str) -> str:
    return f"generated/fix-demo-{case}"


def source_diff(before: dict[str, str], after: dict[str, str]) -> list[str]:
    lines = []
    for path in sorted(before.keys() | after.keys()):
        old, new = before.get(path, ""), after.get(path, "")
        if old != new:
            lines += difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{path}", f"b/{path}",
                                          lineterm="", n=1)
    return lines


def main(argv: list[str], llm=None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Fix loop: test -> fix -> apply -> test until green")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--case", choices=sorted(CASES), help="broken fixture to write and fix (default phaser-default)")
    source.add_argument("--project-dir", help="existing project below generated/ or games/")
    parser.add_argument("--target-dir", help="where to write --case (default generated/fix-demo-<case>)")
    parser.add_argument("--max-fix-attempts", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="print the final GameFactoryState as JSON")
    parser.add_argument("--model", help=f"Ollama model (default: $GAME_FACTORY_MODEL, else .env; now {model_name()})")
    parser.add_argument("--from-decision", action="store_true",
                        help="with --project-dir: give the human note of `decide.py changes` to the fixer, then "
                             "test / review / gate again (M22)")
    parser.add_argument("--run-id", help="run log folder name below logs/runs/ (default: time + project name); "
                                         "a run with an injected test LLM is logged only with --run-id")
    args = parser.parse_args(argv[1:])
    with_log = llm is None or args.run_id is not None
    if args.from_decision and not args.project_dir:
        parser.error("--from-decision needs --project-dir")
    if args.target_dir and args.project_dir:
        parser.error("--target-dir is for --case; use --project-dir alone for an existing project")
    if not 0 <= args.max_fix_attempts <= MAX_FIX_ATTEMPTS_LIMIT:
        parser.error(f"--max-fix-attempts must be between 0 and {MAX_FIX_ATTEMPTS_LIMIT}")

    case = None
    before = project_hashes(root)
    try:
        if args.project_dir:
            target = check_fix_target(args.project_dir, root)
            written: list[str] = []
        else:
            case = CASES[args.case or "phaser-default"]()
            target = check_target(args.target_dir or default_case_target(case.name), root)
            changes = [FileChange(path=p, operation="create", content=c, reason=f"fixture {case.name}")
                       for p, c in case.files.items()]
            result = apply_changes(changes, target, apply=True, root=root)
            if not result.ok:
                print(f"error: {result.summary()}")
                return 1
            written = result.changed_files
        sources_before = read_project(target, root)
    except SafetyError as exc:
        print(f"error: target refused: {exc}\nnothing was run or written")
        return 2

    label = f"{case.name}: {case.description}" if case else target
    if not args.json:
        print(f"=== PROJECT ({label}) ===\n{target}/ · {len(sources_before)} source files"
              + (f" · fixture written ({len(written)} files)" if case else ""))
    saved = None if case else saved_spec_and_plan(target, root)  # M21c: the project's own spec
    spec, plan = saved if saved else (sample_game_spec(), sample_task_plan())
    if not args.json and not case:
        print(f"spec: {spec.title}" + ("" if saved else " (no saved state: sample spec)"))
    state = GameFactoryState(
        user_idea=f"fix loop on {label}",
        game_spec=spec,
        task_plan=plan,
        target_dir=target,
        changed_files=written,
        max_fix_attempts=args.max_fix_attempts,
        status=FactoryStatus.CHANGES_APPLIED if case else FactoryStatus.TESTING,
    )
    entry = "test_runner"
    if args.from_decision:
        try:
            saved = load_state(target, root)
        except (SafetyError, ValueError) as exc:
            print(f"error: {exc}")
            return 2
        decision = saved.human_decision
        if saved.status != FactoryStatus.NEEDS_CHANGES or not decision or not decision.note:
            print(f"error: {target} has no 'changes' decision with a note; first run: "
                  f"python scripts/decide.py --project-dir {target} changes --note \"what to change\"")
            return 2
        state = saved.model_copy(update={
            "test_result": human_review_failure(decision.note), "status": FactoryStatus.TESTS_FAILED,
            "fix_attempts": 0, "max_fix_attempts": args.max_fix_attempts, "loop_history": [], "fix_records": [],
            "fix_changes": [], "review_result": None, "human_decision": None, "error": None})
        entry = "fixer"
        if not args.json:
            print(f"human note for the fixer: {decision.note}")
    if llm is None and args.model:
        llm = make_llm(args.model)
    if not args.json:
        print(f"model: {model_name(args.model)}", flush=True)
    log = None
    if with_log:  # M21b: live log of nodes and LLM calls (stderr with --json)
        echo = (lambda line: print(line, file=sys.stderr, flush=True)) if args.json else \
            (lambda line: print(line, flush=True))
        try:
            log = open_run_log(root, args.run_id, Path(target).name, model_name(args.model),
                               f"fix loop on {target}" + (" (human note)" if args.from_decision else ""), echo=echo)
        except ValueError as exc:
            print(f"error: {exc}")
            return 2
        echo(f"run log: {log.dir.relative_to(root)}/run.log (LLM calls: llm/; viewer: scripts/show_run.py)")
    start = time.monotonic()
    state = run_fix_loop(state, llm=llm, root=root, start=entry, log=log)
    elapsed = time.monotonic() - start
    after = project_hashes(root)
    inside, outside = _apply_proof(before, after, target)
    sources = [p for p in inside if not any(skip in p for skip in PROJECT_SKIP)]

    if args.json:
        print(state.model_dump_json(indent=2, exclude_none=True))
    else:
        print("\n=== FIX LOOP ===", *format_loop(state), sep="\n")
        diff = source_diff(sources_before, read_project(target, root))
        print("\n=== SOURCE CHANGES MADE BY THE LOOP ===", *(diff or ["(none)"]), sep="\n")
        if state.review_result:
            print("\n=== REVIEW ===", *format_review(state.review_result), sep="\n")
        if state.status in GATE_STATUSES:
            print("\n=== HUMAN REVIEW ===", *format_gate(state), sep="\n")
        print(f"\n=== RESULT ===\nstatus: {state.status.value} · fix attempts {state.fix_attempts}/"
              f"{state.max_fix_attempts} · {elapsed:.1f}s")
        if state.error:
            print(f"error: {state.error}")
        print(f"files changed inside {target}/: {len(inside)} ({len(sources)} source files; "
              f"the rest are test runner outputs and .factory/state.json)\nfiles changed outside it: {len(outside)}"
              + "".join(f"\n  OUTSIDE  {p}" for p in outside))
    return 0 if gate_passed(state) and not outside else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
