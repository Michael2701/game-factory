"""Generate the minimal target project (M10) and build it.

Usage (from project root; npm install needs network):
    python scripts/generate_sample_game.py                         # generated/sample-game
    python scripts/generate_sample_game.py --target generated/x --dry-run
    python scripts/generate_sample_game.py --no-install --no-build

Files go through the applier (agents/tools/apply_changes.py), commands through the safe
tools (agents/tools/commands.py). Exit code 0 only if every step succeeded.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.generators.minimal_project import generate_minimal_project  # noqa: E402
from agents.tools.safety import SafetyError  # noqa: E402


def tail(text: str, lines: int = 8) -> str:
    return "\n".join("      " + line for line in text.strip().splitlines()[-lines:])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate and build the minimal Vite + TS target project")
    parser.add_argument("--target", default="generated/sample-game")
    parser.add_argument("--dry-run", action="store_true", help="only show what would be written")
    parser.add_argument("--no-install", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args(argv[1:])

    try:
        report = generate_minimal_project(args.target, apply=not args.dry_run,
                                          install=not args.no_install, build=not args.no_build)
    except SafetyError as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 2

    print(report.preview.summary())
    if report.applied:
        print(f"\nwritten: {len(report.applied.changed_files)} file(s)")
    for result in report.commands:
        status = "ok" if result.ok else f"FAILED (exit {result.exit_code})"
        print(f"\n$ {result.command}   [{status}, {result.duration_s:.1f}s, cwd {result.cwd}]")
        if result.stdout.strip():
            print(tail(result.stdout))
        if not result.ok and result.stderr.strip():
            print(tail(result.stderr, 20))
    if report.dist_files:
        print("\ndist/: " + ", ".join(report.dist_files))
    print(f"\nRESULT: {'ok' if report.ok else 'FAILED — ' + report.error}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
