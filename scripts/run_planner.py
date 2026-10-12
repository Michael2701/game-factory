"""Run the planner node on a game idea and print the validated GameSpec.

Usage (from project root, Ollama running):
    python scripts/run_planner.py "A simple game where the player dodges falling blocks for 60 seconds."

Exit code 0 + GameSpec JSON on success; exit code 1 + NodeError JSON on failure.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.nodes.planner import plan_game  # noqa: E402
from agents.schemas import NodeError  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    result = plan_game(argv[1])
    print(result.model_dump_json(indent=2))
    return 1 if isinstance(result, NodeError) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
