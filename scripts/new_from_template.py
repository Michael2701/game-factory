"""Create a project from the Phaser + Vite template (M19) and optionally check it.

Usage (from project root):
    python scripts/new_from_template.py --target generated/template-check            # write only
    python scripts/new_from_template.py --target generated/template-check --check    # + install, build, Playwright
    python scripts/new_from_template.py --target generated/x --slug my-game --title "My Game"

Writes the instantiated template (package name = slug, page title = title) into a NEW or
empty folder below generated/ or games/ through the applier (preview, then write). With
--check it runs the test runner (npm install -> npm run build -> Playwright) and prints the
TestResult. Exit code 0 on success (and passing checks), 1 when the write or the checks fail,
2 when the target is refused (nothing written).
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.generators.phaser_template import DEFAULT_TEMPLATE, LOCKED_FILES, template_changes  # noqa: E402
from agents.nodes import test_runner  # noqa: E402
from agents.nodes.applier import TARGET_REFUSED, check_target  # noqa: E402
from agents.tools.apply_changes import apply_changes  # noqa: E402
from agents.tools.safety import SafetyError  # noqa: E402


def main(argv: list[str], root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Instantiate the Phaser + Vite template into a new project folder")
    parser.add_argument("--target", required=True, help="new or empty folder below generated/ or games/")
    parser.add_argument("--slug", help="package name (default: the target folder name)")
    parser.add_argument("--title", help="page title (default: from the slug)")
    parser.add_argument("--check", action="store_true", help="run npm install, npm run build and Playwright")
    args = parser.parse_args(argv[1:])

    try:
        target = check_target(args.target, root)
    except SafetyError as exc:
        print(f"error: {TARGET_REFUSED}: {exc}\nnothing was written")
        return 2
    slug = args.slug or target.rsplit("/", 1)[-1]
    title = args.title or slug.replace("-", " ").title()
    result = apply_changes(template_changes(slug, title), target, apply=True, root=root)
    if not result.ok:
        print(f"error: {result.summary()}")
        return 1
    print(f"=== TEMPLATE {DEFAULT_TEMPLATE} → {target}/ ===")
    for path in result.changed_files:
        rel = path.removeprefix(f"{target}/")
        print(f"WROTE  {rel}" + ("   (locked)" if rel in LOCKED_FILES else ""))
    if not args.check:
        return 0

    checks = test_runner.run_project_checks(target, root=root)
    print(f"\n=== CHECKS ===\nstatus: {checks.status} ({checks.summary})")
    for failure in checks.failures[:3]:
        print(f"  failure: {failure.name}: {failure.message.strip()[:500]}")
    return 0 if checks.status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
