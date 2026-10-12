"""Reviewer node (M17): GameSpec + project files summary + TestResult -> structured ReviewResult.

Never writes files. Deterministic facts (build/test outcome, test hooks, file layout) are
computed first (`review_facts`), shown to the model as ground truth and enforced by the
semantic check (`check_review`): the model's judgement may not contradict them, a verdict
must follow from the checks, and issues may only name files that exist. Errors feed the
repair prompt. The node leaves `status` unchanged — mapping the verdict to a human review
state is M18. Reference: docs/NODES.md.
"""

import re
from pathlib import Path

from agents.llm import invoke_structured, make_llm
from agents.nodes.fixer import PATH_IN_OUTPUT
from agents.nodes.test_runner import COMMANDS
from agents.nodes.test_writer import TEST_CALL
from agents.prompts import format_files, render_prompt
from agents.schemas import FactoryStatus, GameFactoryState, GameSpec, NodeError, ReviewResult, TestResult
from agents.tools.filesystem import read_project
from agents.tools.safety import PROJECT_ROOT, SafetyError

NODE = "reviewer"

REVIEW_CHECKS = ("scope_small", "testable", "test_hooks_present", "browser_game_suitable",
                 "no_obvious_ux_issues", "files_organized")
HOOKS = ("__GAME_STATE__", "__TEST_API__")
MAX_SUMMARY_CHARS = 16000  # file contents shown to the model; the tree is always complete
# Files a small Vite + Phaser + Playwright project may have outside src/ and tests/.
ROOT_FILES = frozenset({"package.json", "index.html", "tsconfig.json", "vite.config.ts", "vite.config.js",
                        "playwright.config.ts"})
SCENE_CLASS = re.compile(r"\bextends\s+(?:Phaser\.)?Scene\b")
TESTS_COUNT = re.compile(r"tests (\d+)/(\d+) passed")
# An issue may name a file that is not in the project only to say that it is missing.
MISSING = re.compile(r"\bmissing\b|does not exist|doesn't exist|not found|absent", re.IGNORECASE)


def _is_spec(path: str) -> bool:
    return path.startswith("tests/") and path.endswith(".spec.ts")


def files_summary(project_files: dict[str, str], max_chars: int = MAX_SUMMARY_CHARS) -> str:
    """Tree with line counts + file contents (src, tests, root config) up to `max_chars`."""
    tree = "\n".join(f"{path}  ({len(text.splitlines())} lines)" for path, text in sorted(project_files.items()))
    order = sorted(project_files, key=lambda p: (not p.startswith("src/"), not _is_spec(p), p))
    shown, omitted, used = {}, [], 0
    for path in order:
        size = len(project_files[path])
        if used + size > max_chars:
            omitted.append(path)
            continue
        shown[path] = project_files[path]
        used += size
    parts = [f"File tree:\n{tree}", format_files(shown)]
    if omitted:
        parts.append("(content omitted for size: " + ", ".join(omitted) + ")")
    return "\n\n".join(parts)


def review_facts(project_files: dict[str, str], result: TestResult) -> dict:
    """Facts about the project and its test run that need no judgement."""
    ran = {c.command: c for c in result.command_results}
    build = ran.get(COMMANDS["build"][0])
    count = TESTS_COUNT.search(result.summary)
    src = "\n".join(t for p, t in project_files.items() if p.startswith("src/"))
    specs = "\n".join(t for p, t in project_files.items() if _is_spec(p))
    scene_files = sorted(p for p, t in project_files.items() if p.startswith("src/") and SCENE_CLASS.search(t))
    stray = sorted(p for p in project_files
                   if p not in ROOT_FILES and not p.startswith(("src/", "tests/", "public/")))
    return {
        "test_status": result.status,
        "test_summary": result.summary,
        # passed = every step that ran succeeded; None = the build did not run (e.g. install failed)
        "build_ok": build.ok if build is not None else (True if result.status == "passed" else None),
        "tests_ran": COMMANDS["test"][0] in ran or count is not None,
        "tests_passed": f"{count.group(1)}/{count.group(2)}" if count else None,
        "test_count": sum(len(TEST_CALL.findall(t)) for p, t in project_files.items() if _is_spec(p)),
        "hooks_defined_in_src": {h: h in src for h in HOOKS},
        "hooks_used_in_tests": {h: h in specs for h in HOOKS},
        "test_hooks_present": all(h in src and h in specs for h in HOOKS),
        "scene_files": scene_files,
        "scenes_outside_src_scenes": [p for p in scene_files if not p.startswith("src/scenes/")],
        "stray_files": stray,
    }


def check_review(review: ReviewResult, facts: dict, project_files: dict[str, str]) -> list[str]:
    """Semantic rules for a ReviewResult. Returns error strings (empty = ok)."""
    errors = []
    names = [c.name for c in review.checks]
    if names != list(REVIEW_CHECKS):
        errors.append(f"checks: expected exactly these names in this order {list(REVIEW_CHECKS)}, got {names}")
    checks = {c.name: c for c in review.checks}
    failed = [c.name for c in review.checks if not c.passed]

    def expect(name: str, passed: bool, why: str):
        if name in checks and checks[name].passed != passed:
            errors.append(f"checks.{name}: passed must be {str(passed).lower()} — {why}")

    expect("test_hooks_present", facts["test_hooks_present"],
           f"facts: hooks defined in src {facts['hooks_defined_in_src']}, used in tests {facts['hooks_used_in_tests']}")
    if facts["build_ok"] is False or facts["test_status"] == "error":
        expect("browser_game_suitable", False, "the project does not build or could not be run")
    if facts["scenes_outside_src_scenes"] or facts["stray_files"]:
        expect("files_organized", False, f"scenes outside src/scenes {facts['scenes_outside_src_scenes']}, "
                                         f"stray files {facts['stray_files']}")

    if review.verdict == "approve":
        if failed:
            errors.append(f"verdict: 'approve' requires every check to pass; failed: {failed}")
        if facts["test_status"] != "passed":
            errors.append(f"verdict: 'approve' requires passed tests; test status is '{facts['test_status']}'")
    elif not failed and facts["test_status"] == "passed":
        errors.append("verdict: all checks passed and tests passed, so the verdict must be 'approve'")
    if facts["build_ok"] is False and review.verdict != "reject":
        errors.append("verdict: the project does not build, so the verdict must be 'reject'")
    if review.verdict != "approve" and not review.issues:
        errors.append(f"issues: verdict '{review.verdict}' needs at least one concrete issue (file + what is wrong)")

    texts = [("issues", i, text) for i, text in enumerate(review.issues)]
    texts += [(f"checks.{c.name}.note", None, c.note) for c in review.checks]
    for field, index, text in texts:
        unknown = [p for p in PATH_IN_OUTPUT.findall(text) if p not in project_files]
        if unknown and not MISSING.search(text):
            where = f"{field}.{index}" if index is not None else field
            errors.append(f"{where}: names files that are not in the project {unknown}; "
                          "refer to files from the file tree, or say the file is missing (e.g. '<path>: missing, …')")
    return errors


def review(spec: GameSpec, project_files: dict[str, str], result: TestResult, llm=None) -> ReviewResult | NodeError:
    """Review a generated project against its GameSpec and TestResult."""
    if not project_files:
        return NodeError(node=NODE, message="project has no source files to review")
    facts = review_facts(project_files, result)
    schema = ReviewResult.model_json_schema()
    prompt = render_prompt(
        "reviewer",
        game_spec=spec,
        files_summary=files_summary(project_files),
        test_result={"status": result.status, "summary": result.summary,
                     "failures": [{"name": f.name, "message": f.message[-1000:]} for f in result.failures]},
        facts=facts,
        schema=schema,
    )
    return invoke_structured(llm or make_llm(), NODE, prompt, ReviewResult, schema,
                             check=lambda r: check_review(r, facts, project_files))


def reviewer_node(state: GameFactoryState, llm=None, root: Path = PROJECT_ROOT) -> dict:
    """LangGraph node: review `state.target_dir` (read-only); sets `review_result`, keeps `status`."""
    def error(message: str) -> dict:
        err = NodeError(node=NODE, message=message)
        return {"status": FactoryStatus.ERROR, "error": f"{NODE}: {err.model_dump_json()}"}

    if state.game_spec is None or state.test_result is None:
        return error("state needs game_spec and test_result; run the test runner first")
    if not state.target_dir:
        return error("state has no target_dir; nothing to review")
    try:
        project_files = read_project(state.target_dir, root)
    except SafetyError as exc:
        return error(f"cannot read project {state.target_dir}: {exc}")

    result = review(state.game_spec, project_files, state.test_result, llm)
    if isinstance(result, NodeError):
        return {"status": FactoryStatus.ERROR, "error": f"{NODE}: {result.model_dump_json()}"}
    return {"review_result": result, "error": None}
