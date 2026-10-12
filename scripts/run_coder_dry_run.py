"""Run the coder node in dry-run mode on one task and show the proposed file changes.

Usage (from project root, Ollama running):
    python scripts/run_coder_dry_run.py                      # sample Block Dodger spec + plan, task T3
    python scripts/run_coder_dry_run.py --task T4
    python scripts/run_coder_dry_run.py --spec spec.json --plan plan.json --task T2
    python scripts/run_coder_dry_run.py --json               # FileChangeSet JSON only

Proves that nothing is written: hashes every project file before and after the run.
Exit code 0 on valid changes with an unchanged filesystem; 1 on NodeError or if any
file changed; 2 on usage / bad input files / unknown task id.
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pydantic import ValidationError  # noqa: E402

from agents.nodes.coder import code_task, is_coder_task  # noqa: E402
from agents.schemas import GameSpec, NodeError, TaskPlan  # noqa: E402
from agents.schemas.examples import sample_game_spec, sample_task_plan  # noqa: E402
from agents.tools.filesystem import file_hashes  # noqa: E402


def load(path: Path | None, model, default):
    if path is None:
        return default
    return model.model_validate_json(path.read_text())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Coder dry run: task -> proposed FileChanges")
    parser.add_argument("--spec", type=Path, help="GameSpec JSON file (default: sample Block Dodger)")
    parser.add_argument("--plan", type=Path, help="TaskPlan JSON file (default: sample Block Dodger plan)")
    parser.add_argument("--task", default="T3", help="task id (default: T3)")
    parser.add_argument("--json", action="store_true", help="print only the FileChangeSet JSON")
    args = parser.parse_args(argv[1:])

    try:
        spec = load(args.spec, GameSpec, sample_game_spec())
        plan = load(args.plan, TaskPlan, sample_task_plan())
    except (OSError, ValidationError) as exc:
        print(f"bad input file: {exc}", file=sys.stderr)
        return 2
    task = next((t for t in plan.tasks if t.id == args.task), None)
    if task is None:
        print(f"unknown task id {args.task!r}; plan has {[t.id for t in plan.tasks]}", file=sys.stderr)
        return 2

    before = file_hashes(ROOT)
    start = time.monotonic()
    result = code_task(task, spec)
    elapsed = time.monotonic() - start
    unchanged = file_hashes(ROOT) == before

    if args.json:
        print(result.model_dump_json(indent=2))
    elif isinstance(result, NodeError):
        print(result.model_dump_json(indent=2))
    else:
        print(f"=== TASK {task.id} ({task.kind}): {task.title} ===")
        print(f"allowed paths: {task.target_files or '-'}")
        if not is_coder_task(task):
            print("(not a coding task: no file changes proposed, LLM not called)")
        for change in result.changes:
            body = change.content if change.content is not None else change.patch
            print(f"\n--- {change.operation.upper()} {change.path}  ({len(body.splitlines())} lines)")
            print(f"reason: {change.reason}")
            print(body.rstrip())
        print(f"\n=== DRY RUN ===\nproposed changes: {len(result.changes)} · {elapsed:.1f}s")
        print(f"filesystem unchanged: {'yes' if unchanged else 'NO'} ({len(before)} project files hashed before/after)")

    if not unchanged:
        print("ERROR: project files changed during a dry run", file=sys.stderr)
        return 1
    return 1 if isinstance(result, NodeError) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
