"""Minimal target project generator (M10): a plain Vite + TypeScript placeholder.

Deterministic (no LLM). Produces the target output format as FileChange objects,
writes them through the applier and builds with the safe command tools:

    minimal_project_changes -> apply_changes -> npm install -> npm run build -> dist/index.html

Reference: docs/GENERATORS.md.
"""

import json
from pathlib import Path

from pydantic import BaseModel, Field

from agents.schemas import CommandResult, FileChange, FileChangeSet
from agents.tools.apply_changes import ApplyResult, apply_changes
from agents.tools.commands import run_command
from agents.tools.safety import PROJECT_ROOT, ensure_writable

# Exact pins (reproducible installs); chosen 2026-10-11, each release >= 2 weeks old.
VITE_VERSION = "8.3.1"
TYPESCRIPT_VERSION = "6.0.3"

INSTALL_TIMEOUT_S = 600
BUILD_TIMEOUT_S = 300


def _package_json(slug: str) -> str:
    data = {
        "name": slug,
        "version": "0.0.0",
        "private": True,
        "type": "module",
        "scripts": {"dev": "vite", "build": "vite build"},
        "devDependencies": {"typescript": TYPESCRIPT_VERSION, "vite": VITE_VERSION},
    }
    return json.dumps(data, indent=2) + "\n"


def _index_html(title: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
"""


def _main_ts(title: str) -> str:
    return f"""declare global {{
  interface Window {{
    __GAME_STATE__?: {{ ready: boolean; title: string }};
  }}
}}

const app = document.querySelector<HTMLDivElement>('#app');
if (app) {{
  app.textContent = {json.dumps(title)};
}}

window.__GAME_STATE__ = {{ ready: true, title: {json.dumps(title)} }};

export {{}};
"""


def minimal_project_changes(slug: str, title: str, existing: set[str] | frozenset[str] = frozenset()) -> FileChangeSet:
    """The 3 project files as FileChanges; `update` for paths in `existing`, else `create`."""
    files = {
        "package.json": _package_json(slug),
        "index.html": _index_html(title),
        "src/main.ts": _main_ts(title),
    }
    return FileChangeSet(changes=[
        FileChange(
            path=path,
            operation="update" if path in existing else "create",
            content=content,
            reason=f"M10 minimal project: {path}",
        )
        for path, content in files.items()
    ])


class GenerationReport(BaseModel):
    target_dir: str
    preview: ApplyResult
    applied: ApplyResult | None = None
    commands: list[CommandResult] = Field(default_factory=list)
    dist_files: list[str] = Field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def generate_minimal_project(
    target: str = "generated/sample-game",
    *,
    slug: str | None = None,
    title: str | None = None,
    apply: bool = True,
    install: bool = True,
    build: bool = True,
    root: Path = PROJECT_ROOT,
) -> GenerationReport:
    """Preview + apply the files, then npm install and npm run build. Stops at the first failure."""
    root = Path(root).resolve()
    target_path = ensure_writable(target, root)
    slug = slug or target_path.name
    title = title or slug.replace("-", " ").title()
    existing = {p for p in ("package.json", "index.html", "src/main.ts") if (target_path / p).is_file()}
    changes = minimal_project_changes(slug, title, existing)

    preview = apply_changes(changes, target, root=root)
    report = GenerationReport(target_dir=preview.target_dir, preview=preview)
    if not preview.ok:
        report.error = "invalid file changes: " + "; ".join(preview.errors)
        return report
    if not apply:
        return report

    report.applied = apply_changes(changes, target, apply=True, root=root)
    if not report.applied.ok:
        report.error = "apply failed: " + "; ".join(report.applied.errors)
        return report

    steps = []
    if install:
        steps.append(("npm install", INSTALL_TIMEOUT_S))
    if build:
        steps.append(("npm run build", BUILD_TIMEOUT_S))
    for command, timeout in steps:
        result = run_command(command, target, timeout=timeout, root=root)
        report.commands.append(result)
        if not result.ok:
            report.error = f"'{command}' failed with exit code {result.exit_code}" + (" (timed out)" if result.timed_out else "")
            return report

    if build:
        dist = target_path / "dist"
        report.dist_files = sorted(p.relative_to(dist).as_posix() for p in dist.rglob("*") if p.is_file())
        if "index.html" not in report.dist_files:
            report.error = "build finished but dist/index.html is missing"
    return report
