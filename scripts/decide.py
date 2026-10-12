"""Record a human decision at the approval gate (M18), or show the gate.

Usage (from project root; no Ollama, no npm):
    python scripts/decide.py --project-dir generated/fix-demo-two-bugs --show
    python scripts/decide.py --project-dir generated/fix-demo-two-bugs approve [--note "fun"]
    python scripts/decide.py --project-dir generated/fix-demo-two-bugs changes --note "add a restart key"
    python scripts/decide.py --project-dir generated/fix-demo-two-bugs reject --note "not a game"

Loads <project>/.factory/state.json (written by the human gate at the end of the fix loop),
applies the decision (needs_human_review -> approved / needs_changes / rejected), saves the
file and prints the next actions. A decision is taken once; approve needs passing tests.
Exit code 0 on success, 1 when the saved state is missing or invalid,
2 on usage error or a refused decision (nothing written).
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.nodes.applier import check_fix_target  # noqa: E402
from agents.nodes.human_gate import GateError, decide, format_gate, load_state, save_state  # noqa: E402
from agents.tools.safety import SafetyError  # noqa: E402

CHOICES = {"approve": "approve", "reject": "reject", "changes": "needs_changes"}


def main(argv: list[str], root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Human approval gate: approve / reject / request changes")
    parser.add_argument("--project-dir", required=True, help="project below generated/ or games/ that reached the gate")
    parser.add_argument("decision", nargs="?", choices=sorted(CHOICES), help="omit with --show")
    parser.add_argument("--note", default="", help="why; recommended for changes / reject")
    parser.add_argument("--show", action="store_true", help="only print the gate status and next actions")
    args = parser.parse_args(argv[1:])
    if args.show == bool(args.decision):
        parser.error("give a decision (approve / reject / changes) or --show")
    if args.show and args.note:
        parser.error("--note needs a decision")

    try:
        target = check_fix_target(args.project_dir, root)
    except SafetyError as exc:
        print(f"error: {exc}\nnothing was written")
        return 2
    try:
        state = load_state(target, root)
    except (SafetyError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    if args.decision:
        try:
            state = decide(state, CHOICES[args.decision], args.note.strip())
        except GateError as exc:
            print(f"error: {exc}\nnothing was written")
            return 2
        print(f"saved: {save_state(state, root)}")
    print("=== HUMAN REVIEW ===", *format_gate(state), sep="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
