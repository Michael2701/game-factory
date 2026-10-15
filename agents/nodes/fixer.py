"""Fixer node (M15): failing TestResult + project files -> minimal proposed FileChanges.

Never writes files: the result is a proposal for the applier (fix loop, M16). The model
only sees and may only change the files relevant to the failure (`relevant_files`); a new
file may be created only when the error output names it and it does not exist. Minimality
and "do not weaken tests" are checked deterministically (`check_fix`), errors feed the
repair prompt. Reference: docs/NODES.md.
"""

import difflib
import hashlib
import json
import re
from pathlib import Path

from agents.llm import invoke_structured, make_llm
from agents.generators.phaser_template import locked_files
from agents.nodes.coder import hook_properties, phaser_problems
from agents.nodes.test_writer import TEST_CALL
from agents.prompts import format_files, render_prompt
from agents.schemas import (
    FactoryStatus,
    FileChange,
    FileChangeSet,
    FixRecord,
    GameFactoryState,
    GameSpec,
    NodeError,
    TaskPlan,
    TestResult,
)
from agents.tools.filesystem import read_project
from agents.tools.safety import PROJECT_ROOT, SafetyError, package_json_problems

NODE = "fixer"

ALWAYS_RELEVANT = ("package.json", "src/main.ts")  # entry point + dependencies: needed for most build errors
MAX_FILES = 3
MIN_LINE_BUDGET = 20  # changed lines (added + removed) allowed per file ...
LINE_BUDGET_SHARE = 0.4  # ... or this share of the file's lines, whichever is larger
MAX_FAILURE_CHARS = 1500  # per failure, tail (M21: was 4000)
MAX_FAILURES = 5
MAX_STACK_FRAMES = 8  # per error
MAX_RELEVANT_CHARS = 24_000  # file contents shown to the fixer; overflow files are listed, not updatable

# --- anti-repeat (M21) ----------------------------------------------------------------
COMMENT_LINE = re.compile(r"^(//|/\*|\*)")
SIGNATURE_NOISE = re.compile(r"index-[\w-]+\.js|\d+")


def normalize_lines(text: str) -> list[str]:
    """Code lines with whitespace collapsed; blank and comment-only lines dropped."""
    lines = (" ".join(line.split()) for line in text.splitlines())
    return [line for line in lines if line and not COMMENT_LINE.match(line)]


def fingerprint(changes: list[FileChange]) -> str:
    """sha256 of the normalized change set: whitespace/comment variants of a fix are the same fix."""
    data = sorted((c.path, normalize_lines(c.content or "")) for c in changes)
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()


def changed_line_set(old: str, new: str) -> set[str]:
    """Normalized lines a change adds or removes."""
    return set(normalize_lines(old)) ^ set(normalize_lines(new))


def failure_signature(result: TestResult) -> str:
    """The first failure, without numbers / bundle hashes: equal signatures = the same error."""
    if not result.failures:
        return SIGNATURE_NOISE.sub("#", result.summary)
    first = result.failures[0]
    line = next((l.strip() for l in first.message.splitlines() if l.strip()), "")
    return SIGNATURE_NOISE.sub("#", f"{first.name} | {line}")[:300]


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


def budget_files(files: dict[str, str], first: list[str], max_chars: int = MAX_RELEVANT_CHARS) -> dict[str, str]:
    """Keep files in priority order (`first`, then src/, then the rest) until `max_chars` (M21)."""
    order = list(dict.fromkeys([*(p for p in first if p in files), *sorted(p for p in files if p.startswith("src/")),
                                *sorted(files)]))
    kept, used = {}, 0
    for path in order:
        if kept and used + len(files[path]) > max_chars:
            continue
        kept[path], used = files[path], used + len(files[path])
    return kept


def relevant_files(result: TestResult, project_files: dict[str, str],
                   widen: bool = False) -> tuple[dict[str, str], list[str]]:
    """(files the fixer sees and may update, new files it may create).

    Files named in the failure + package.json + src/main.ts. If the failure names no source
    file under src/ (e.g. a failing Playwright test), every project file is relevant except
    playwright.config.ts, which is relevant only when the failure names it.
    Paths named in the failure that do not exist may be created (e.g. playwright.config.ts).
    """
    mentioned = mentioned_paths(result)
    creatable = [p for p in mentioned if p not in project_files]
    if widen:  # M21: the same error survived a fix -> every src/ file (+ what the failure names), within budget
        wide = {p: c for p, c in project_files.items() if p.startswith("src/") or p in mentioned}
        return budget_files(wide, mentioned), creatable
    if not any(p.startswith("src/") and p in project_files for p in mentioned):
        return budget_files({p: c for p, c in project_files.items() if p != TEST_CONFIG or p in mentioned},
                            mentioned), creatable
    keep = [p for p in mentioned if p in project_files] + [p for p in ALWAYS_RELEVANT if p in project_files]
    return {p: project_files[p] for p in dict.fromkeys(keep)}, creatable


def changed_lines(old: str, new: str) -> int:
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
    return sum(1 for line in diff if line[:1] in "+-" and not line.startswith(("+++", "---")))


def line_budget(old: str) -> int:
    return max(MIN_LINE_BUDGET, int(len(old.splitlines()) * LINE_BUDGET_SHARE))


def check_fix(changes: FileChangeSet, relevant: dict[str, str], creatable: list[str],
              locked: tuple[str, ...] | list[str] = (), seen: dict[str, int] | None = None,
              blocked: set[str] | None = None) -> list[str]:
    """`seen`: fingerprint -> attempt of earlier proposals; `blocked`: normalized lines that earlier
    fixes changed without changing the error (M21 anti-repeat)."""
    """Semantic rules for a proposed fix. Returns error strings (empty = ok; no changes = gave up)."""
    errors = []
    paths = [c.path for c in changes.changes]
    for path in sorted({p for p in paths if paths.count(p) > 1}):
        errors.append(f"changes: duplicate change for '{path}'")
    if len(set(paths)) > MAX_FILES:
        errors.append(f"changes: {len(set(paths))} files changed; a minimal fix changes at most {MAX_FILES} files")

    for i, change in enumerate(changes.changes):
        where = f"changes.{i} ({change.path})"
        if change.path in locked:  # M21: template config, browser-error fixtures, the acceptance test
            errors.append(f"{where}: '{change.path}' is locked (read-only); fix the game code under src/ instead")
            continue
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
        if change.path.endswith(".ts") and not _is_test_file(change.path):
            new_code = "\n".join(added_lines(relevant.get(change.path, ""), content))
            project_code = "\n".join([*(c for p, c in relevant.items() if p.endswith(".ts")), content])
            errors += phaser_problems(where, new_code, project_code, file_code=content)  # what the fix adds (M20)
        if not exists:
            continue

        old = relevant[change.path]
        count = changed_lines(old, content)
        if count == 0:
            errors.append(f"{where}: content is identical to the current file; change it or leave it out")
        elif normalize_lines(old) == normalize_lines(content):
            errors.append(f"{where}: changes only whitespace or comments; that cannot fix the error")
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
    if changes.changes and not errors:
        earlier = (seen or {}).get(fingerprint(changes.changes))
        if earlier is not None:
            errors.append(f"changes: the same fix as attempt {earlier} (ignoring whitespace and comments); it did not "
                          "solve the failure, so change something else")
        touched = set().union(*(changed_line_set(relevant.get(c.path, ""), c.content or "") for c in changes.changes))
        if blocked and touched and touched <= blocked:
            errors.append("changes: only touches lines that earlier fixes already changed without any effect on this "
                          "error; the cause is elsewhere: look at other lines or files (e.g. the scene that owns the "
                          "failing key handler, hook or game object)")
    return errors


def _trim_stack(message: str) -> str:
    """At most MAX_STACK_FRAMES `at ...` lines per error."""
    out, frames = [], 0
    for line in message.splitlines():
        if line.lstrip().startswith("at "):
            frames += 1
            if frames > MAX_STACK_FRAMES:
                continue
        else:
            frames = 0
        out.append(line)
    return "\n".join(out)


def _trimmed_failures(result: TestResult) -> list[dict]:
    """At most MAX_FAILURES distinct failures, stacks shortened, each message's last MAX_FAILURE_CHARS chars."""
    seen, out = set(), []
    for failure in result.failures:
        message = _trim_stack(failure.message)[-MAX_FAILURE_CHARS:]
        if (failure.name, message) in seen:
            continue
        seen.add((failure.name, message))
        out.append({"name": failure.name, "message": message})
    return out[:MAX_FAILURES]


HOOK_READ = re.compile(r"__(GAME_STATE|TEST_API)__\??\.(\w+)")


def hook_hints(result: TestResult, project_files: dict[str, str]) -> list[str]:
    """Deterministic diagnosis (M21): hooks the failing tests read that no src/ hook object defines."""
    hook_src = {p: c for p, c in project_files.items()
                if p.startswith("src/") and ("__GAME_STATE__" in c or "__TEST_API__" in c)}
    if not hook_src:
        return []
    defined = set().union(*(hook_properties(c) for c in hook_src.values()))
    used = dict.fromkeys(HOOK_READ.findall(_failure_text(result)))
    return [f"The failing test reads window.__{obj}__.{name}, but the hooks in {', '.join(sorted(hook_src))} do not "
            f"define `{name}` (defined: {', '.join(sorted(defined))}). Add `{name}` to that hook object (e.g. a getter "
            "returning the scene's value) instead of changing the game logic."
            for obj, name in used if name not in defined]


def _failure_view(result: TestResult, project_files: dict[str, str] | None = None) -> dict:
    """Compact TestResult for the prompt: failures and failed commands, no install logs (+ hook hints, M21)."""
    hints = hook_hints(result, project_files or {})
    return {
        **({"hints": hints} if hints else {}),
        "status": result.status,
        "summary": result.summary,
        "failed_commands": [{"command": c.command, "exit_code": c.exit_code, "timed_out": c.timed_out}
                            for c in result.command_results if not c.ok],
        "failures": _trimmed_failures(result),
    }


def fix(
    result: TestResult,
    project_files: dict[str, str],
    spec: GameSpec,
    plan: TaskPlan | None = None,
    fix_attempt: int = 1,
    max_fix_attempts: int = 5,
    llm=None,
    previous_attempts: list[str] | None = None,
    locked: tuple[str, ...] | list[str] = (),
    records: list[FixRecord] | None = None,
) -> FileChangeSet | NodeError:
    """Propose a minimal fix for a failed TestResult. An empty FileChangeSet means: no safe fix.

    `previous_attempts` (M20): one line per earlier step of this fix loop, so the model does not
    repeat a change that did not help.
    """
    records = records or []
    signature = failure_signature(result)
    no_effect = [r for r in records if r.no_effect and r.signature == signature]
    seen = {r.fingerprint: r.attempt for r in records}
    blocked = set().union(*(r.lines for r in no_effect)) if no_effect else set()
    relevant, creatable = relevant_files(result, project_files, widen=bool(no_effect))
    schema = FileChangeSet.model_json_schema()
    prompt = render_prompt(
        "fixer",
        test_result=_failure_view(result, project_files),
        project_tree=sorted(project_files),
        relevant_files=format_files(relevant),
        new_files=creatable or "(none)",
        game_spec=spec,
        task_plan=plan if plan is not None else "(not available)",
        fix_attempt=fix_attempt,
        max_fix_attempts=max_fix_attempts,
        previous_attempts=previous_attempts or "(none: this is the first attempt)",
        schema=schema,
    )
    return invoke_structured(llm or make_llm(), NODE, prompt, FileChangeSet, schema,
                             check=lambda changes: check_fix(changes, relevant, creatable, locked, seen, blocked))


def attempt_history(state: GameFactoryState) -> list[str]:
    """Earlier fix-loop steps after the first test run, one line each (shown to the fixer, M20),
    plus the fixes that did NOT change the error, with the lines they touched (M21)."""
    lines = [f"#{s.attempt} {s.step} {s.status}: {s.summary[:300]}" + (f" [{', '.join(s.files)}]" if s.files else "")
             for s in state.loop_history if s.attempt > 0]
    for r in state.fix_records:
        touched = "; ".join(r.lines[:6]) + (" ..." if len(r.lines) > 6 else "")
        if r.made_worse:  # M21b: the graph undid it, the project is back to the state before it
            lines.append(f"#{r.attempt} made the tests WORSE and was undone (the files are back as before it); "
                         f"do not repeat it. It touched: {touched}")
        elif r.no_effect:
            lines.append(f"#{r.attempt} did NOT change the error ({r.signature[:160]}); it touched: {touched}")
    return lines


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
    proposal = fix(result, project_files, state.game_spec, state.task_plan, attempt, state.max_fix_attempts, llm,
                   previous_attempts=attempt_history(state), locked=locked_files(state.template),
                   records=state.fix_records)
    if isinstance(proposal, NodeError):
        proposal = proposal.model_copy(update={"message": f"attempt {attempt}: {proposal.message}"})
        return {"fix_attempts": attempt, "status": FactoryStatus.ERROR, "error": f"{NODE}: {proposal.model_dump_json()}"}
    if not proposal.changes:
        out = error(f"attempt {attempt}: the model found no safe fix")
        return {**out, "fix_attempts": attempt, "fix_changes": []}
    touched = set().union(*(changed_line_set(project_files.get(c.path, ""), c.content or "")
                            for c in proposal.changes))
    record = FixRecord(attempt=attempt, fingerprint=fingerprint(proposal.changes), signature=failure_signature(result),
                       lines=sorted(touched)[:200])
    return {"fix_attempts": attempt, "fix_changes": proposal.changes, "fix_records": [*state.fix_records, record],
            "status": FactoryStatus.FIXING, "error": None}
