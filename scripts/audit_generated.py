"""Audit a generated project for manual edits (M21).

Usage (from project root):
    python scripts/audit_generated.py --project-dir generated/block-dodger-m21-r7

Compares every source file (read_project view) with .factory/manifest.json, which the applier
writes after each agent write (apply_changes, apply_fix). Any difference means the sources were
changed outside the agent pipeline. Exit 0 = matches, 1 = differences or no manifest,
2 = bad project dir.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.nodes.applier import MANIFEST_FILE, check_fix_target, source_hashes  # noqa: E402
from agents.tools.filesystem import read_file  # noqa: E402
from agents.tools.safety import SafetyError  # noqa: E402


def main(argv: list[str], root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Check a generated project against its agent-write manifest")
    parser.add_argument("--project-dir", required=True)
    args = parser.parse_args(argv[1:])
    try:
        target = check_fix_target(args.project_dir, root)
    except SafetyError as exc:
        print(f"error: {exc}")
        return 2
    try:
        manifest = json.loads(read_file(f"{target}/{MANIFEST_FILE}", root))
    except (SafetyError, ValueError) as exc:
        print(f"error: no readable manifest ({exc}); the project was not written by the M21 pipeline")
        return 1
    expected, current = manifest["files"], source_hashes(target, root)
    diff = sorted(p for p in expected.keys() | current.keys() if expected.get(p) != current.get(p))
    print(f"manifest: {len(expected)} files, last written by {manifest.get('written_by')}")
    for path in diff:
        state = "missing" if path not in current else "added" if path not in expected else "changed"
        print(f"  {state.upper():8}{path}")
    print("no manual edits: yes" if not diff else f"no manual edits: NO ({len(diff)} file(s) differ)")
    return 0 if not diff else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
