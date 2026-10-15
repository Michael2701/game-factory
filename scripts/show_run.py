"""Show a run log (M21b): what the graph and the LLM did during a run. Read-only.

Usage (from project root):
    python scripts/show_run.py                      # list runs, newest last
    python scripts/show_run.py <run-id>             # the timeline (run.log)
    python scripts/show_run.py <run-id> --follow    # keep printing new lines (Ctrl+C to stop)
    python scripts/show_run.py <run-id> --llm 3     # LLM call 3 in full: prompt, reasoning, reply, errors
    python scripts/show_run.py latest ...           # the newest run

Logs live in logs/runs/<run-id>/ (git-ignored); see agents/run_log.py.
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.run_log import LOG_DIR, run_dir  # noqa: E402


def runs(root: Path) -> list[str]:
    base = root / LOG_DIR
    return sorted(p.name for p in base.iterdir() if (p / "run.log").is_file()) if base.is_dir() else []


def main(argv: list[str], root: Path = ROOT, follow_seconds: float | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show a run log: node timeline or one LLM call")
    parser.add_argument("run_id", nargs="?", help="run folder below logs/runs/, or 'latest'")
    parser.add_argument("--follow", action="store_true", help="keep printing new lines")
    parser.add_argument("--llm", type=int, metavar="N", help="print LLM call N in full")
    args = parser.parse_args(argv[1:])

    known = runs(root)
    if not args.run_id:
        print("\n".join(known) if known else f"no runs in {LOG_DIR}/")
        return 0
    run_id = known[-1] if args.run_id == "latest" and known else args.run_id
    try:
        directory = run_dir(root, run_id)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    if not (directory / "run.log").is_file():
        print(f"error: no run log {LOG_DIR}/{run_id}/run.log")
        return 2

    if args.llm is not None:
        calls = sorted((directory / "llm").glob(f"{args.llm:03d}-*.md"))
        if not calls:
            print(f"error: no LLM call {args.llm} in {LOG_DIR}/{run_id}/llm/")
            return 2
        print(calls[0].read_text(encoding="utf-8"))
        return 0

    with open(directory / "run.log", encoding="utf-8") as f:
        print(f.read(), end="", flush=True)
        if not args.follow:
            return 0
        deadline = None if follow_seconds is None else time.monotonic() + follow_seconds  # tests stop early
        try:
            while deadline is None or time.monotonic() < deadline:
                line = f.readline()
                if line:
                    print(line, end="", flush=True)
                    if " END " in line:
                        return 0
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
