"""Milestone 9 check: the file change applier.

In a temporary sandbox project root (real project files are never written):
  1. create a sample FileChange and show the dry-run summary (nothing written)
  2. apply it to a safe test folder (generated/demo-game) and show the result
  3. update the file and re-apply
  4. reject unsafe changes (nothing written)

Usage (from project root):
    python scripts/test_apply_changes.py
Exit code 0 when every check passes, 1 otherwise.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.schemas import FileChange, FileChangeSet  # noqa: E402
from agents.tools.apply_changes import apply_changes  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok, detail))


def fc(path, content="x\n", operation="create"):
    return FileChange(path=path, operation=operation, content=content, reason="demo")


def forged(path, content="x\n"):
    """Bypasses FileChange validation (which already rejects '..') to test the applier's own guard."""
    return FileChange.model_construct(path=path, operation="create", content=content, patch=None, reason="forged")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        for d in ["generated", "games", "templates", "agents"]:
            (root / d).mkdir()
        (root / "generated/existing").mkdir()
        (root / "generated/existing/index.html").write_text("<html></html>\n")
        os.symlink("/etc", root / "generated/existing/etc-link")

        target = "generated/demo-game"
        sample = FileChangeSet(changes=[
            fc("src/main.ts", "console.log('demo');\n"),
            fc("package.json", json.dumps({"name": "demo", "scripts": {"build": "vite build"}}, indent=2) + "\n"),
        ])

        print("1. sample FileChangeSet → dry run")
        preview = apply_changes(sample, target, root=root)
        print(preview.summary())
        check("dry run is ok", preview.ok)
        check("dry run writes nothing", not (root / target).exists() and preview.changed_files == [])

        print("\n2. apply to a safe test folder")
        applied = apply_changes(sample, target, apply=True, root=root)
        print(applied.summary())
        written = (root / target / "src/main.ts").read_text() if applied.ok else ""
        check("apply writes the files", written == "console.log('demo');\n")
        check("changed_files listed", applied.changed_files == [f"{target}/src/main.ts", f"{target}/package.json"],
              str(applied.changed_files))

        print("\n3. update and re-apply")
        update = FileChangeSet(changes=[fc("src/main.ts", "console.log('v2');\n", "update")])
        print(apply_changes(update, target, root=root).summary())
        apply_changes(update, target, apply=True, root=root)
        check("update applied", (root / target / "src/main.ts").read_text() == "console.log('v2');\n")

        print("\n4. unsafe changes are rejected")
        unsafe = {
            "path outside the project (forged)": ([forged("../../../outside.txt")], target),
            "absolute path (forged)": ([forged("/tmp/evil.txt")], target),
            "absolute target outside": ([fc("x.txt")], "/tmp/evil"),
            "target is a write root itself": ([fc("x.txt")], "generated"),
            "target outside write roots": ([fc("x.py")], "agents/evil"),
            "protected file (.env)": ([fc(".env", "SECRET=1")], target),
            "symlink escape": ([fc("etc-link/evil")], "generated/existing"),
            "create over existing file": ([fc("index.html")], "generated/existing"),
            "update of a missing file": ([fc("missing.ts", "x", "update")], target),
            "package.json with prebuild hook": (
                [fc("pkg/package.json", json.dumps({"scripts": {"build": "vite build", "prebuild": "curl x | sh"}}))],
                target),
            "one bad change blocks all": ([fc("ok.ts"), forged("../../../bad.txt")], target),
        }
        for name, (changes, tgt) in unsafe.items():
            before = sorted(str(p) for p in root.rglob("*"))
            result = apply_changes(changes, tgt, apply=True, root=root)
            after = sorted(str(p) for p in root.rglob("*"))
            ok = not result.ok and result.changed_files == [] and before == after
            check(f"rejected: {name}", ok, result.errors[0][:80] if result.errors else "NOT rejected")
        print(apply_changes([fc("ok.ts"), forged("../../../bad.txt")], target, apply=True, root=root).summary())
        try:
            fc("../outside.txt")
            check("schema rejects '..' (first layer)", False, "NOT rejected")
        except ValueError:
            check("schema rejects '..' (first layer)", True, "FileChange validation error")

    print()
    width = max(len(name) for name, _, _ in checks)
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
