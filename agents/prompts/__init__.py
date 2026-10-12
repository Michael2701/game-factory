"""Prompt templates for agent roles. Reference: docs/PROMPTS.md.

Templates are Markdown files in this directory with `{{name}}` placeholders
(double braces, because prompts contain JSON). Rendering is strict: every
placeholder must be supplied, and no unknown variables are accepted.
"""

import json
import re
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parent
PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")

PROMPT_NAMES = ("planner", "task_decomposer", "coder", "test_writer", "fixer", "reviewer", "repair")


def load_prompt(name: str) -> str:
    if name not in PROMPT_NAMES:
        raise ValueError(f"unknown prompt: {name!r}; expected one of {PROMPT_NAMES}")
    return (PROMPTS_DIR / f"{name}.md").read_text()


def prompt_variables(name: str) -> set[str]:
    return set(PLACEHOLDER.findall(load_prompt(name)))


def _to_text(value: Any) -> str:
    """Strings pass through; Pydantic models and plain data become pretty JSON."""
    if isinstance(value, str):
        return value
    if hasattr(value, "model_dump_json"):
        return value.model_dump_json(indent=2, exclude_none=True)
    return json.dumps(value, indent=2, ensure_ascii=False)


def render_prompt(name: str, **variables: Any) -> str:
    template = load_prompt(name)
    expected = set(PLACEHOLDER.findall(template))
    missing = expected - variables.keys()
    unknown = variables.keys() - expected
    if missing or unknown:
        raise ValueError(f"prompt {name!r}: missing={sorted(missing)} unknown={sorted(unknown)}")
    return PLACEHOLDER.sub(lambda m: _to_text(variables[m.group(1)]), template)


def format_files(files: dict[str, str]) -> str:
    """Render {path: content} as readable blocks for prompts (JSON would escape newlines).

    Uses '=== path ===' headers rather than markdown fences, so the model is not
    nudged into putting fences inside file content.
    """
    if not files:
        return "(none)"
    return "\n\n".join(f"=== {path} ===\n{content.rstrip()}\n=== end of {path} ===" for path, content in files.items())
