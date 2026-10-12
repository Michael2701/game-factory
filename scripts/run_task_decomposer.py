"""Run the task decomposer node on a GameSpec and print the validated TaskPlan.

Usage (from project root, Ollama running):
    python scripts/run_task_decomposer.py                    # sample Block Dodger GameSpec
    python scripts/run_task_decomposer.py --spec spec.json   # GameSpec JSON file

Exit code 0 + TaskPlan JSON on success; 1 + NodeError JSON on failure; 2 on usage / bad spec file.
The node only plans: no files are written.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402

from agents.nodes.task_decomposer import decompose  # noqa: E402
from agents.schemas import GameSpec, NodeError  # noqa: E402
from agents.schemas.examples import sample_game_spec  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="GameSpec -> TaskPlan")
    parser.add_argument("--spec", type=Path, help="GameSpec JSON file (default: sample Block Dodger spec)")
    args = parser.parse_args(argv[1:])

    if args.spec:
        try:
            spec = GameSpec.model_validate_json(args.spec.read_text())
        except (OSError, ValidationError) as exc:
            print(f"bad --spec file: {exc}", file=sys.stderr)
            return 2
    else:
        spec = sample_game_spec()

    result = decompose(spec)
    print(result.model_dump_json(indent=2))
    return 1 if isinstance(result, NodeError) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
