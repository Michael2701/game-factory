"""Test runner node (M12): run install / build / Playwright tests on a generated project.

Deterministic (no LLM). All commands go through the safe tools. Result is a TestResult:
  passed  - every step that ran succeeded
  failed  - a step exited non-zero (build error, failing test, bad dependency) -> fixable
  error   - could not run (missing project, SafetyError, timeout)
Reference: docs/NODES.md.
"""

import json
import re
from pathlib import Path

from agents.schemas import CommandResult, FactoryStatus, GameFactoryState, TestFailure, TestResult
from agents.tools.commands import MAX_OUTPUT_CHARS, run_command, tail_output
from agents.tools.sourcemap import map_frames
from agents.tools.safety import PROJECT_ROOT, SafetyError, ensure_allowed_path

STEPS = ("install", "build", "test")
# The JSON report grows ~5 KB per failing test; the 20k default tail cut it (found in M19, 9 tests = 46 KB).
REPORT_MAX_CHARS = 5_000_000
# M21: the test build keeps names + source maps (template vite.config.ts); `npm run build` alone stays minified.
DEBUG_BUILD_ENV = {"GAME_FACTORY_DEBUG_BUILD": "1"}
COMMANDS = {
    "install": ("npm install", 600),
    "build": ("npm run build", 300),
    "test": ("npx playwright test --reporter=json", 600),
}
FAILURE_TAIL_LINES = 40
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def default_project_dir(slug: str) -> str:
    return f"generated/{slug}"


NOISE = re.compile(r"^\s+at .*node_modules|^\s*errors: \[Getter/Setter\]|^\}$")


def _tail(result: CommandResult, lines: int = FAILURE_TAIL_LINES) -> str:
    """stderr then stdout, ANSI stripped, without node_modules stack frames (noise for the fixer)."""
    text = ANSI.sub("", (result.stderr.strip() + "\n" + result.stdout.strip()).strip())
    kept = [line for line in text.splitlines() if not NOISE.search(line)]
    return "\n".join(kept[-lines:]) or f"exit code {result.exit_code}"


def _walk_specs(suite: dict, prefix: str = ""):
    title = suite.get("title", "")
    path = f"{prefix} › {title}" if prefix and title else (title or prefix)
    for spec in suite.get("specs", []):
        yield path, spec
    for child in suite.get("suites", []):
        yield from _walk_specs(child, path)


def parse_playwright_json(stdout: str) -> tuple[int, list[TestFailure]] | None:
    """(number of specs, failures) from `--reporter=json` output; None if unparsable."""
    start = stdout.find("{")
    if start == -1:
        return None
    try:
        report = json.loads(stdout[start:])
    except json.JSONDecodeError:
        return None
    total, failures = 0, []
    for suite in report.get("suites", []):
        for path, spec in _walk_specs(suite):
            total += 1
            if spec.get("ok", True):
                continue
            messages = []
            for test in spec.get("tests", []):
                for result in test.get("results", []):
                    for err in result.get("errors", []) or ([result["error"]] if result.get("error") else []):
                        messages.append(err.get("message", ""))
            message = ANSI.sub("", "\n".join(m for m in messages if m)).strip() or "test failed"
            failures.append(TestFailure(name=f"{path} › {spec.get('title', '?')}", message=message[:4000]))
    for err in report.get("errors", []):
        failures.append(TestFailure(name="playwright", message=ANSI.sub("", err.get("message", "error"))[:4000]))
    return total, failures


def _has_tests(project: Path) -> bool:
    return any((project / "tests").glob("*.spec.ts")) if (project / "tests").is_dir() else False


def run_project_checks(project_dir: str, steps: tuple[str, ...] = STEPS, root: Path = PROJECT_ROOT) -> TestResult:
    unknown = [s for s in steps if s not in STEPS]
    if unknown:
        return TestResult(status="error", summary=f"unknown steps {unknown}; allowed {list(STEPS)}")
    try:
        project = ensure_allowed_path(project_dir, root)
    except SafetyError as exc:
        return TestResult(status="error", summary=f"project dir rejected: {exc}")
    if not (project / "package.json").is_file():
        return TestResult(status="error", summary=f"no package.json in {project_dir}")

    results: list[CommandResult] = []
    notes: list[str] = []
    for step in STEPS:
        if step not in steps:
            continue
        if step == "test" and not _has_tests(project):
            notes.append("no tests found (tests/*.spec.ts)")
            continue
        command, timeout = COMMANDS[step]
        try:
            limit = REPORT_MAX_CHARS if step == "test" else MAX_OUTPUT_CHARS
            env = DEBUG_BUILD_ENV if step == "build" else None
            result = run_command(command, project_dir, timeout=timeout, root=root, max_output_chars=limit,
                                 extra_env=env)
        except SafetyError as exc:
            notes.append(f"{step} rejected")
            return TestResult(status="error", command_results=results,
                              summary=" · ".join(notes + [f"{command}: {exc}"]))
        report = result.stdout  # full Playwright JSON for parsing; the stored result is shortened
        result = result.model_copy(update={"stdout": tail_output(result.stdout)})
        results.append(result)

        if result.timed_out:
            notes.append(f"{step} timed out after {timeout}s")
            return TestResult(status="error", command_results=results, summary=" · ".join(notes))

        if step == "test":
            parsed = parse_playwright_json(report)
            if parsed is None:
                if result.ok:
                    notes.append("tests ok (report not parsed)")
                    continue
                notes.append("tests failed (report not parsed)")
                return TestResult(status="failed", command_results=results, summary=" · ".join(notes),
                                  failures=[TestFailure(name=command, message=_tail(result))])
            total, failures = parsed
            # browser stack frames in the bundle -> src/… positions (best effort, M21)
            failures = [f.model_copy(update={"message": map_frames(f.message, project)}) for f in failures]
            notes.append(f"tests {total - len([f for f in failures if f.name != 'playwright'])}/{total} passed")
            if failures or not result.ok:
                failures = failures or [TestFailure(name=command, message=_tail(result))]
                return TestResult(status="failed", command_results=results, failures=failures,
                                  summary=" · ".join(notes))
            continue

        if not result.ok:
            notes.append(f"{step} failed (exit {result.exit_code})")
            return TestResult(status="failed", command_results=results, summary=" · ".join(notes),
                              failures=[TestFailure(name=command, message=_tail(result))])
        notes.append(f"{step} ok")

    return TestResult(status="passed", command_results=results, summary=" · ".join(notes))


def test_runner_node(state: GameFactoryState, project_dir: str | None = None, root: Path = PROJECT_ROOT) -> dict:
    """LangGraph node: run checks on the game's project and record the TestResult.

    Project: `project_dir`, else `state.target_dir` (the applied project, M16), else generated/<slug>.
    """
    project_dir = project_dir or state.target_dir
    if project_dir is None:
        if state.game_spec is None:
            result = TestResult(status="error", summary="no project_dir and no game_spec to derive it from")
            return {"test_result": result, "status": FactoryStatus.ERROR, "error": f"test_runner: {result.summary}"}
        project_dir = default_project_dir(state.game_spec.slug)
    result = run_project_checks(project_dir, root=root)
    status = {"passed": FactoryStatus.TESTS_PASSED, "failed": FactoryStatus.TESTS_FAILED,
              "error": FactoryStatus.ERROR}[result.status]
    update = {
        "test_result": result,
        "command_results": [*state.command_results, *result.command_results],
        "status": status,
    }
    update["error"] = f"test_runner: {result.summary}" if result.status == "error" else None
    return update


test_runner_node.__test__ = False  # not a unittest/pytest test despite the name
