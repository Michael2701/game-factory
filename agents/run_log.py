"""Run log (M21b): what the graph and the LLM do during a run, written while it happens.

    logs/runs/<run-id>/
      run.log             one human-readable line per finished node and per LLM call (`tail -f`)
      events.jsonl        the same events as JSON lines (machine-readable; Studio streams them later)
      llm/NNN-<node>.md   one file per LLM call: prompt, the model's reasoning, raw reply, errors

The active log is held in a context variable, so nodes and `invoke_structured` need no extra
argument; without an active log nothing is written. `logs/` is git-ignored and lies outside
the apply target (which must be new/empty). Viewer: scripts/show_run.py.
"""

import contextvars
import json
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = "logs/runs"
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

_active: contextvars.ContextVar["RunLog | None"] = contextvars.ContextVar("run_log", default=None)


def new_run_id(label: str = "run") -> str:
    """`20261015-143005-block-dodger`: local time + a slug of `label`."""
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40] or "run"
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slug}"


def run_dir(root: Path, run_id: str) -> Path:
    """`root/logs/runs/<run_id>`; refuses ids that are not a plain name (no paths, no traversal)."""
    if not RUN_ID.match(run_id) or ".." in run_id:
        raise ValueError(f"invalid run id (letters, digits, '.', '_', '-'): {run_id!r}")
    return Path(root) / LOG_DIR / run_id


def current() -> "RunLog | None":
    return _active.get()


@contextmanager
def active(log: "RunLog | None") -> Iterator["RunLog | None"]:
    """Make `log` the active run log inside the block (None: no logging)."""
    token = _active.set(log)
    try:
        yield log
    finally:
        _active.reset(token)


def _clip(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_event(event: dict) -> str:
    """One run.log line for an event."""
    clock = event["ts"][11:19]
    kind = event["kind"]
    if kind == "node":
        return f"{clock} {event['node']:<20} {event['duration_s']:>7.1f}s  {event['summary']}"
    if kind == "llm":
        result = "ok" if event["ok"] else "invalid: " + _clip("; ".join(event["errors"]), 120)
        repair = " (repair)" if event["attempt"] > 1 else ""
        return (f"{clock}   llm {event['node']}{repair} {event['duration_s']:.1f}s "
                f"{event['prompt_chars']}→{event['reply_chars']} chars, reasoning {event['reasoning_chars']}: "
                f"{result}  [{event['file']}]")
    if kind == "start":
        return f"{clock} START run {event['run_id']} · model {event['model']} · {_clip(event['what'], 100)}"
    if kind == "end":
        error = f" · error: {_clip(event['error'], 200)}" if event.get("error") else ""
        return f"{clock} END   status {event['status']} · {event['duration_s']:.0f}s{error}"
    return f"{clock} {kind} {_clip(json.dumps({k: v for k, v in event.items() if k not in ('ts', 'kind')}))}"


class RunLog:
    """Writes events (run.log + events.jsonl) and LLM call files below one run directory."""

    def __init__(self, directory: Path, echo: Callable[[str], None] | None = None):
        self.dir = Path(directory)
        (self.dir / "llm").mkdir(parents=True, exist_ok=True)
        self.echo = echo  # e.g. print to the terminal as well
        self.llm_calls = 0

    def event(self, kind: str, **data) -> dict:
        record = {"ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), "kind": kind, **data}
        with open(self.dir / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        line = format_event(record)
        with open(self.dir / "run.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if self.echo:
            self.echo(line)
        return record

    def llm_call(self, node: str, attempt: int, prompt: str, reply: str | None, reasoning: str,
                 errors: list[str], duration_s: float) -> dict:
        """Write llm/NNN-<node>.md with everything about one call, then log a short `llm` event."""
        self.llm_calls += 1
        name = f"llm/{self.llm_calls:03d}-{node}.md"
        verdict = "valid" if not errors else "invalid"
        parts = [f"# {node} · call {self.llm_calls} · {'repair' if attempt > 1 else 'first'} attempt · "
                 f"{duration_s:.1f}s · {verdict}", ""]
        if errors:
            parts += ["## Errors (parse / check)", "", *[f"- {e}" for e in errors], ""]
        parts += ["## Reasoning (model thinking)", "", reasoning.strip() or "(none returned)", "",
                  "## Reply", "", "````", (reply or "(no reply)").strip(), "````", "",
                  "## Prompt", "", "````", prompt.strip(), "````", ""]
        (self.dir / name).write_text("\n".join(parts), encoding="utf-8")
        return self.event("llm", node=node, call=self.llm_calls, attempt=attempt, ok=not errors,
                          errors=errors[:5], duration_s=round(duration_s, 1), prompt_chars=len(prompt),
                          reply_chars=len(reply or ""), reasoning_chars=len(reasoning), file=name)


class Timer:
    """Seconds since the last `lap()` (or creation)."""

    def __init__(self):
        self.start = self.last = time.monotonic()

    def lap(self) -> float:
        now = time.monotonic()
        elapsed, self.last = now - self.last, now
        return elapsed

    def total(self) -> float:
        return time.monotonic() - self.start
