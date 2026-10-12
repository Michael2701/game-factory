"""Safe command execution for agents: allowlisted argv, no shell, scrubbed env.

Reference: docs/TOOLS.md.
"""

import os
import re
import subprocess
import time
from pathlib import Path

from agents.schemas import CommandResult
from agents.tools.safety import PROJECT_ROOT, check_command, ensure_allowed_path

MAX_OUTPUT_CHARS = 20_000
SECRET_ENV = re.compile(r"TOKEN|SECRET|KEY|PASSWORD|PASSWD|CREDENTIAL|AUTH", re.I)


def safe_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}


def tail_output(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Last `limit` characters of a command output, marked when cut."""
    return text if len(text) <= limit else "…[truncated]\n" + text[-limit:]


def run_command(
    command: str | list[str],
    cwd: str | Path = ".",
    timeout: float = 300,
    root: Path = PROJECT_ROOT,
    max_output_chars: int = MAX_OUTPUT_CHARS,
) -> CommandResult:
    """Run an allowlisted command. Raises SafetyError before running anything unsafe.

    stdout/stderr keep their last `max_output_chars` characters (callers that parse a large
    report, e.g. the Playwright JSON, raise the limit and shorten the result themselves).
    """
    def _tail(text: str) -> str:
        return tail_output(text, max_output_chars)

    argv = check_command(command, cwd, root)
    cwd_path = ensure_allowed_path(cwd, root)
    display = command if isinstance(command, str) else " ".join(command)
    rel_cwd = cwd_path.relative_to(Path(root).resolve()).as_posix()
    start = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=cwd_path, capture_output=True, text=True,
                              timeout=timeout, env=safe_env(), shell=False)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
        err = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr or ""
        return CommandResult(command=display, cwd=rel_cwd, exit_code=-1, stdout=_tail(out),
                             stderr=_tail(err + f"\n[timed out after {timeout}s]"),
                             duration_s=time.monotonic() - start, timed_out=True)
    return CommandResult(command=display, cwd=rel_cwd, exit_code=proc.returncode,
                         stdout=_tail(proc.stdout), stderr=_tail(proc.stderr),
                         duration_s=time.monotonic() - start)
