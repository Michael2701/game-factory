"""Run the fixer node in dry-run mode and show the proposed fix as a diff.

Usage (from project root, Ollama running):
    python scripts/run_fixer_dry_run.py                                   # synthetic case phaser-default
    python scripts/run_fixer_dry_run.py --case import-case
    python scripts/run_fixer_dry_run.py --project-dir generated/block-dodger   # real: install + build + tests first
    python scripts/run_fixer_dry_run.py --json                            # FileChangeSet JSON only

Synthetic cases (agents/fixtures/broken_projects.py) live in memory: nothing is read from or
written to disk, and the fix is judged deterministically ("plausible": the culprit file changed
in the right way). --project-dir runs the real test runner (npm install, build, Playwright —
these write node_modules/dist/test reports), then proves the FIXER wrote nothing.
Exit code 0 on a non-empty, valid (and, for cases, plausible) fix with an unchanged
filesystem; 1 otherwise (NodeError, no fix, implausible, files changed, tests passed);
2 on usage / bad input.
"""

import argparse
import difflib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.fixtures.broken_projects import CASES  # noqa: E402
from agents.nodes.fixer import changed_lines, fix, relevant_files  # noqa: E402
from agents.nodes.test_runner import run_project_checks  # noqa: E402
from agents.schemas import NodeError  # noqa: E402
from agents.schemas.examples import sample_game_spec, sample_task_plan  # noqa: E402
from agents.tools.filesystem import file_hashes, read_project  # noqa: E402
from agents.tools.safety import SafetyError  # noqa: E402


def main(argv: list[str], llm=None) -> int:
    parser = argparse.ArgumentParser(description="Fixer dry run: failing TestResult -> proposed minimal fix")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--case", choices=sorted(CASES), help="synthetic broken project (default phaser-default)")
    source.add_argument("--project-dir", help="real project: run install/build/tests, then propose a fix")
    parser.add_argument("--json", action="store_true", help="print only the FileChangeSet JSON")
    args = parser.parse_args(argv[1:])

    case = None
    if args.project_dir:
        result = run_project_checks(args.project_dir)
        if result.status != "failed":
            print(f"test runner: {result.status} — {result.summary}; nothing to fix")
            return 1
        try:
            files = read_project(args.project_dir)
        except SafetyError as exc:
            print(f"bad input: {exc}", file=sys.stderr)
            return 2
    else:
        case = CASES[args.case or "phaser-default"]()
        result, files = case.test_result, case.files

    relevant, creatable = relevant_files(result, files)
    before = file_hashes(ROOT)
    start = time.monotonic()
    proposal = fix(result, files, sample_game_spec(), sample_task_plan(), llm=llm)
    elapsed = time.monotonic() - start
    unchanged = file_hashes(ROOT) == before

    if args.json or isinstance(proposal, NodeError):
        print(proposal.model_dump_json(indent=2))
        return 0 if not isinstance(proposal, NodeError) and proposal.changes and unchanged else 1

    print(f"=== FAILURE ({case.name + ': ' + case.description if case else args.project_dir}) ===")
    print(result.summary)
    for failure in result.failures:
        print(f"- {failure.name}: " + "\n  ".join(failure.message.strip().splitlines()[:6]))
    print(f"\nrelevant files: {sorted(relevant)}   may create: {creatable or '-'}")

    print("\n=== PROPOSED FIX ===")
    if not proposal.changes:
        print("(none — the model found no safe fix)")
    for change in proposal.changes:
        old = files.get(change.path, "")
        print(f"{change.operation.upper()} {change.path}  ({changed_lines(old, change.content or '')} changed lines)")
        print(f"reason: {change.reason}")
        diff = difflib.unified_diff(old.splitlines(), (change.content or "").splitlines(),
                                    f"a/{change.path}", f"b/{change.path}", lineterm="", n=1)
        print("\n".join(diff))

    plausible = True
    if case:
        new = {c.path: c.content or "" for c in proposal.changes}
        plausible = case.culprit in new and case.is_fixed(new[case.culprit])
        print(f"\nplausible fix (culprit {case.culprit} fixed): {'yes' if plausible else 'NO'}")
    print(f"\n=== DRY RUN ===\nproposed changes: {len(proposal.changes)} · {elapsed:.1f}s")
    print(f"filesystem unchanged: {'yes' if unchanged else 'NO'} ({len(before)} project files hashed before/after)")
    return 0 if proposal.changes and plausible and unchanged else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
