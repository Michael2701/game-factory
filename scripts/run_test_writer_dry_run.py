"""Run the test writer node in dry-run mode and show the proposed Playwright tests.

Usage (from project root, Ollama running):
    python scripts/run_test_writer_dry_run.py                                # sample Block Dodger spec
    python scripts/run_test_writer_dry_run.py --spec spec.json
    python scripts/run_test_writer_dry_run.py --project-dir generated/sample-game
    python scripts/run_test_writer_dry_run.py --json                         # FileChangeSet JSON only

--project-dir reads the existing project's source files read-only (safe read_file).
Proves that nothing is written: hashes every project file before and after the run.
Exit code 0 on valid tests with an unchanged filesystem; 1 on NodeError or if any file
changed; 2 on usage / bad input.
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pydantic import ValidationError  # noqa: E402

from agents.nodes.test_writer import write_tests  # noqa: E402
from agents.schemas import GameSpec, NodeError  # noqa: E402
from agents.schemas.examples import sample_game_spec  # noqa: E402
from agents.tools.filesystem import file_hashes, read_project  # noqa: E402
from agents.tools.safety import SafetyError  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Test writer dry run: GameSpec -> proposed Playwright tests")
    parser.add_argument("--spec", type=Path, help="GameSpec JSON file (default: sample Block Dodger)")
    parser.add_argument("--project-dir", help="existing project folder to show as context (read-only)")
    parser.add_argument("--json", action="store_true", help="print only the FileChangeSet JSON")
    args = parser.parse_args(argv[1:])

    try:
        spec = GameSpec.model_validate_json(args.spec.read_text()) if args.spec else sample_game_spec()
        project_files = read_project(args.project_dir) if args.project_dir else {}
    except (OSError, ValidationError, SafetyError) as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return 2

    before = file_hashes(ROOT)
    start = time.monotonic()
    result = write_tests(spec, project_files)
    elapsed = time.monotonic() - start
    unchanged = file_hashes(ROOT) == before

    if args.json or isinstance(result, NodeError):
        print(result.model_dump_json(indent=2))
    else:
        print(f"=== TESTS FOR {spec.title} ({spec.slug}) ===")
        print(f"project files shown as context: {sorted(project_files) or '-'}")
        for change in result.changes:
            print(f"\n--- {change.operation.upper()} {change.path}  ({len(change.content.splitlines())} lines)")
            print(f"reason: {change.reason}")
            print(change.content.rstrip())
        print(f"\n=== DRY RUN ===\nproposed changes: {len(result.changes)} · {elapsed:.1f}s")
        print(f"filesystem unchanged: {'yes' if unchanged else 'NO'} ({len(before)} project files hashed before/after)")

    if not unchanged:
        print("ERROR: project files changed during a dry run", file=sys.stderr)
        return 1
    return 1 if isinstance(result, NodeError) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
