"""Fixer node (M15): failing TestResult + project files -> minimal proposed FileChanges.

Never writes files: the result is a proposal for the applier (fix loop, M16). The model
only sees and may only change the files relevant to the failure (`relevant_files`); a new
file may be created only when the error output names it and it does not exist. Minimality
and "do not weaken tests" are checked deterministically (`check_fix`), errors feed the
repair prompt. Reference: docs/NODES.md.
"""

import difflib
import re
from pathlib import Path

from agents.llm import invoke_structured, make_llm
from agents.nodes.test_writer import TEST_CALL
from agents.prompts import format_files, render_prompt
from agents.schemas import FactoryStatus, FileChangeSet, GameFactoryState, GameSpec, NodeError, TaskPlan, TestResult
from agents.tools.filesystem import read_project
from agents.tools.safety import PROJECT_ROOT, SafetyError, package_json_problems

NODE = "fixer"

ALWAYS_RELEVANT = ("package.json", "src/main.ts")  # entry point + dependencies: needed for most build errors
MAX_FILES = 3
MIN_LINE_BUDGET = 20  # changed lines (added + removed) allowed per file ...
LINE_BUDGET_SHARE = 0.4  # ... or this share of the file's lines, whichever is larger
MAX_FAILURE_CHARS = 4000

# Project file paths as they appear in build/test output (also inside absolute paths).
PATH_IN_OUTPUT = re.compile(
    r"(?<![\w-])((?:src|tests)/[\w./-]+?\.(?:ts|js|css|json|html)|package\.json|index\.html"
    r"|playwright\.config\.ts|vite\.config\.ts|tsconfig\.json)\b")
WEAKENING = re.compile(r"\btest\.(skip|only|fixme)\b|\b(describe|it)\.(skip|only)\b")
# Raising a timeout / adding a wait hides a "state never reached" bug instead of fixing it (M16).
TIMEOUT_CHANGE = re.compile(r"timeout|waitForTimeout|setTimeout|test\.slow", re.IGNORECASE)
TEST_CONFIG = "playwright.config.ts"  # only relevant when the failure names it


def _is_test_file(path: str) -> bool:
    return path == TEST_CONFIG or (path.startswith("tests/") and path.endswith(".spec.ts"))


def added_lines(old: str, new: str) -> list[str]:
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
    return [line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")]


def _failure_text(result: TestResult) -> str:
    parts = [f.name + "\n" + f.message for f in result.failures]
    parts += [c.stdout + "\n" + c.stderr for c in result.command_results if not c.ok]
    return "\n".join(parts)


def mentioned_paths(result: TestResult) -> list[str]:
    """Project-relative paths named in the failure output, in order of appearance."""
    seen: list[str] = []
    for path in PATH_IN_OUTPUT.findall(_failure_text(result)):
        if ".." not in path.split("/") and path not in seen:
            seen.append(path)
    return seen


def relevant_files(result: TestResult, project_files: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """(files the fixer sees and may update, new files it may create).

    Files named in the failure + package.json + src/main.ts. If the failure names no source
    file under src/ (e.g. a failing Playwright test), every project file is relevant except
    playwright.config.ts, which is relevant only when the failure names it.
    Paths named in the failure that do not exist may be created (e.g. playwright.config.ts).
    """
    mentioned = mentioned_paths(result)
    creatable = [p for p in mentioned if p not in project_files]
    if not any(p.startswith("src/") and p in project_files for p in mentioned):
        return {p: c for p, c in project_files.items() if p != TEST_CONFIG or p in mentioned}, creatable
    keep = [p for p in mentioned if p in project_files] + [p for p in ALWAYS_RELEVANT if p in project_files]
    return {p: project_files[p] for p in dict.fromkeys(keep)}, creatable


def changed_lines(old: str, new: str) -> int:
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
    return sum(1 for line in diff if line[:1] in "+-" and not line.startswith(("+++", "---")))


def line_budget(old: str) -> int:
    return max(MIN_LINE_BUDGET, int(len(old.splitlines()) * LINE_BUDGET_SHARE))


def check_fix(changes: FileChangeSet, relevant: dict[str, str], creatable: list[str]) -> list[str]:
    """Semantic rules for a proposed fix. Returns error strings (empty = ok; no changes = gave up)."""
    errors = []
    paths = [c.path for c in changes.changes]
    for path in sorted({p for p in paths if paths.count(p) > 1}):
        errors.append(f"changes: duplicate change for '{path}'")
    if len(set(paths)) > MAX_FILES:
        errors.append(f"changes: {len(set(paths))} files changed; a minimal fix changes at most {MAX_FILES} files")

    for i, change in enumerate(changes.changes):
        where = f"changes.{i} ({change.path})"
        if change.path not in relevant and change.path not in creatable:
            errors.append(f"{where}: path is not allowed; you may update {sorted(relevant)}"
                          + (f" or create {creatable}" if creatable else ""))
            continue
        if change.operation == "delete":
            errors.append(f"{where}: delete is not allowed")
            continue
        exists = change.path in relevant
        if change.operation == "create" and exists:
            errors.append(f"{where}: file already exists, use operation 'update'")
        if change.operation == "update" and not exists:
            errors.append(f"{where}: file does not exist yet, use operation 'create'")
        if change.patch is not None:
            errors.append(f"{where}: patch is not supported; send the full file content")
            continue
        content = change.content or ""
        if not content.strip():
            errors.append(f"{where}: content must not be empty")
            continue
        if "```" in content:
            errors.append(f"{where}: content must be raw file text without markdown code fences")
        if change.path.split("/")[-1] == "package.json":
            errors += [f"{where}: {p}" for p in package_json_problems(content, require_build=True)]
        if not exists:
            continue

        old = relevant[change.path]
        count = changed_lines(old, content)
        if count == 0:
            errors.append(f"{where}: content is identical to the current file; change it or leave it out")
        elif count > line_budget(old):
            errors.append(f"{where}: {count} changed lines, a minimal fix changes at most {line_budget(old)}; "
                          "keep every unrelated line exactly as it is and change only the lines causing the error")
        if _is_test_file(change.path) and any(TIMEOUT_CHANGE.search(line) for line in added_lines(old, content)):
            errors.append(f"{where}: raises a timeout or adds a wait; a timeout means the expected state was "
                          "never reached — fix the game code that should reach it instead")
        if change.path.startswith("tests/") and change.path.endswith(".spec.ts"):
            if len(TEST_CALL.findall(content)) < len(TEST_CALL.findall(old)):
                errors.append(f"{where}: removes tests; do not delete tests to make them pass")
            if WEAKENING.search(content) and not WEAKENING.search(old):
                errors.append(f"{where}: test.skip/only/fixme are not allowed; fix the cause instead")
    return errors


def _failure_view(result: TestResult) -> dict:
    """Compact TestResult for the prompt: failures and failed commands, no install logs."""
    return {
        "status": result.status,
        "summary": result.summary,
        "failed_commands": [{"command": c.command, "exit_code": c.exit_code, "timed_out": c.timed_out}
                            for c in result.command_results if not c.ok],
        "failures": [{"name": f.name, "message": f.message[-MAX_FAILURE_CHARS:]} for f in result.failures],
    }


def fix(
    result: TestResult,
    project_files: dict[str, str],
    spec: GameSpec,
    plan: TaskPlan | None = None,
    fix_attempt: int = 1,
    max_fix_attempts: int = 5,
    llm=None,
) -> FileChangeSet | NodeError:
    """Propose a minimal fix for a failed TestResult. An empty FileChangeSet means: no safe fix."""
    relevant, creatable = relevant_files(result, project_files)
    schema = FileChangeSet.model_json_schema()
    prompt = render_prompt(
        "fixer",
        test_result=_failure_view(result),
        project_tree=sorted(project_files),
        relevant_files=format_files(relevant),
        new_files=creatable or "(none)",
        game_spec=spec,
        task_plan=plan if plan is not None else "(not available)",
        fix_attempt=fix_attempt,
        max_fix_attempts=max_fix_attempts,
        schema=schema,
    )
    return invoke_structured(llm or make_llm(), NODE, prompt, FileChangeSet, schema,
                             check=lambda changes: check_fix(changes, relevant, creatable))


def fixer_node(state: GameFactoryState, llm=None, root: Path = PROJECT_ROOT) -> dict:
    """LangGraph node: propose a fix for `state.test_result` in `state.target_dir` (read-only)."""
    def error(message: str) -> dict:
        err = NodeError(node=NODE, message=message)
        return {"status": FactoryStatus.ERROR, "error": f"{NODE}: {err.model_dump_json()}"}

    result = state.test_result
    if result is None or state.game_spec is None:
        return error("state needs test_result and game_spec; run the test runner first")
    if result.status == "passed":
        return error("tests passed; nothing to fix")
    if result.status == "error":
        return error(f"test run could not complete ({result.summary}); not fixable by code changes")
    if state.fix_attempts >= state.max_fix_attempts:
        return error(f"fix attempts exhausted ({state.fix_attempts}/{state.max_fix_attempts})")
    if not state.target_dir:
        return error("state has no target_dir; nothing to read")
    try:
        project_files = read_project(state.target_dir, root)
    except SafetyError as exc:
        return error(f"cannot read project {state.target_dir}: {exc}")

    attempt = state.fix_attempts + 1
    proposal = fix(result, project_files, state.game_spec, state.task_plan, attempt, state.max_fix_attempts, llm)
    if isinstance(proposal, NodeError):
        proposal = proposal.model_copy(update={"message": f"attempt {attempt}: {proposal.message}"})
        return {"fix_attempts": attempt, "status": FactoryStatus.ERROR, "error": f"{NODE}: {proposal.model_dump_json()}"}
    if not proposal.changes:
        out = error(f"attempt {attempt}: the model found no safe fix")
        return {**out, "fix_attempts": attempt, "fix_changes": []}
    return {"fix_attempts": attempt, "fix_changes": proposal.changes, "status": FactoryStatus.FIXING, "error": None}
