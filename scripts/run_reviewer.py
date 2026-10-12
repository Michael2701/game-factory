"""Review an existing generated project (reviewer node, M17).

Usage (from project root, Ollama running, network for npm install):
    python scripts/run_reviewer.py --project-dir generated/fix-demo-two-bugs
    python scripts/run_reviewer.py --project-dir generated/block-dodger --spec spec.json --json

Runs the test runner (install -> build -> Playwright) on the project, then the reviewer:
GameSpec (default: the sample Block Dodger spec) + files summary + TestResult -> ReviewResult.
Prints the facts, the review and a proof that the reviewer changed no file.
Exit code 0 on a valid ReviewResult (any verdict) with nothing changed by the reviewer,
1 on a reviewer error, 2 on usage error (bad project dir, unreadable spec).
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.game_factory_graph import format_review  # noqa: E402
from agents.nodes import test_runner  # noqa: E402
from agents.nodes.applier import check_fix_target  # noqa: E402
from agents.nodes.reviewer import review, review_facts  # noqa: E402
from agents.schemas import GameSpec, NodeError  # noqa: E402
from agents.schemas.examples import sample_game_spec  # noqa: E402
from agents.tools.filesystem import file_hashes, read_project  # noqa: E402
from agents.tools.safety import SafetyError  # noqa: E402


def main(argv: list[str], llm=None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Test + review an existing generated project")
    parser.add_argument("--project-dir", required=True, help="existing project below generated/ or games/")
    parser.add_argument("--spec", help="GameSpec JSON file (default: sample Block Dodger spec)")
    parser.add_argument("--json", action="store_true", help="print only the ReviewResult as JSON")
    args = parser.parse_args(argv[1:])

    try:
        target = check_fix_target(args.project_dir, root)
        spec = GameSpec.model_validate_json(Path(args.spec).read_text()) if args.spec else sample_game_spec()
    except (SafetyError, OSError, ValueError) as exc:
        print(f"error: {exc}\nnothing was run")
        return 2

    result = test_runner.run_project_checks(target, root=root)
    files = read_project(target, root)
    before = file_hashes(root)
    outcome = review(spec, files, result, llm=llm)
    changed = sorted({path for path, _ in file_hashes(root).items() ^ before.items()})

    if isinstance(outcome, NodeError):
        print(f"error: {outcome.model_dump_json(indent=2)}")
        return 1
    if args.json:
        print(outcome.model_dump_json(indent=2))
    else:
        print(f"=== PROJECT ===\n{target}/ · {len(files)} source files · tests: {result.status} ({result.summary})")
        print("\n=== FACTS ===\n" + json.dumps(review_facts(files, result), indent=2))
        print("\n=== REVIEW ===", *format_review(outcome), sep="\n")
        print(f"\nfiles changed by the reviewer: {len(changed)}")
    return 0 if not changed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
