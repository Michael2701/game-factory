"""Run install / build / Playwright tests on a generated project and print the TestResult.

Usage (from project root):
    python scripts/run_test_runner.py                                   # generated/sample-game
    python scripts/run_test_runner.py --project-dir generated/x --steps build,test
    python scripts/run_test_runner.py --json

Exit code 0 when the TestResult status is 'passed', 1 for 'failed', 2 for 'error'.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.nodes.test_runner import STEPS, run_project_checks  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run safe checks on a generated project -> TestResult")
    parser.add_argument("--project-dir", default="generated/sample-game")
    parser.add_argument("--steps", default=",".join(STEPS), help=f"comma-separated subset of {','.join(STEPS)}")
    parser.add_argument("--json", action="store_true", help="print only the TestResult JSON")
    args = parser.parse_args(argv[1:])

    result = run_project_checks(args.project_dir, tuple(s for s in args.steps.split(",") if s))
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        for r in result.command_results:
            state = "ok" if r.ok else ("TIMEOUT" if r.timed_out else f"FAILED (exit {r.exit_code})")
            print(f"$ {r.command}   [{state}, {r.duration_s:.1f}s, cwd {r.cwd}]")
        print(f"\nstatus: {result.status}\nsummary: {result.summary}")
        for f in result.failures:
            print(f"\nFAILURE {f.name}\n" + "\n".join("  " + line for line in f.message.splitlines()))
    return {"passed": 0, "failed": 1, "error": 2}[result.status]


if __name__ == "__main__":
    sys.exit(main(sys.argv))
