"""Shared LLM helpers for agent nodes: model factory and JSON output parsing.

Reference: docs/NODES.md.
"""

import json
import re
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from agents.schemas.node_error import NodeError

MODEL = "qwen2.5-coder:14b"
TEMPERATURE = 0.2

M = TypeVar("M", bound=BaseModel)

FENCED = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)
# A backslash (after an even run of escaped backslashes) followed by a char JSON cannot escape.
INVALID_ESCAPE = re.compile(r'(?<!\\)((?:\\\\)*)\\([^"\\/bfnrtu])')


def make_llm(model: str = MODEL, temperature: float = TEMPERATURE):
    from langchain_ollama import ChatOllama

    return ChatOllama(model=model, temperature=temperature)


def fix_invalid_escapes(text: str) -> str:
    """Keep the backslash of escapes that JSON does not know: `\\'` -> `\\\\'`.

    qwen writes JS/TS code into JSON strings with JS escapes such as `\\'` (in 'don\\'t')
    or regex `\\d`, which are invalid JSON. Escaping the backslash yields exactly the code
    the model meant (`\\'` is an apostrophe in any JS string). Valid JSON is unchanged.
    """
    return INVALID_ESCAPE.sub(r"\1\\\\\2", text)


def extract_json(text: str) -> str:
    """Return the JSON object text from an LLM reply.

    Handles the common qwen habits: ```json fences, prose before/after the object and
    JS-style escapes that are invalid in JSON (`fix_invalid_escapes`).
    Raises ValueError when no JSON object can be found.
    """
    text = fix_invalid_escapes(text.strip())
    fenced = FENCED.search(text)
    if fenced:
        text = fenced.group(1).strip()
    if text.startswith("{"):
        return text
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in model output")
    # raw_decode stops at the end of the first complete object, ignoring trailing prose.
    _, end = json.JSONDecoder().raw_decode(text, start)
    return text[start:end]


def parse_model(text: str, model: type[M]) -> M:
    """extract_json + strict Pydantic validation. Raises ValueError / ValidationError."""
    return model.model_validate_json(extract_json(text))


def format_errors(exc: Exception) -> list[str]:
    """Human/LLM-readable errors: 'field.path: message' for ValidationError, str otherwise."""
    if isinstance(exc, ValidationError):
        return [f"{'.'.join(map(str, e['loc'])) or '<root>'}: {e['msg']}" for e in exc.errors()]
    return [str(exc)]


def invoke_structured(
    llm,
    node: str,
    prompt: str,
    model: type[M],
    schema: dict,
    check: Callable[[M], list[str]] | None = None,
) -> "M | NodeError":
    """Call the LLM and return a validated `model`, or a NodeError. Never raises.

    invoke -> parse (+ semantic `check`, which returns error strings) -> on errors one
    repair call with the `repair` prompt -> parse/check again -> NodeError if still bad.
    """
    from agents.prompts import render_prompt

    def attempt(raw: str) -> tuple[M | None, list[str]]:
        try:
            result = parse_model(raw, model)
        except ValueError as exc:  # includes ValidationError and JSON errors
            return None, format_errors(exc)
        problems = check(result) if check else []
        return (None, problems) if problems else (result, [])

    attempts, raw = 0, None
    try:
        attempts += 1
        raw = llm.invoke(prompt).content
        result, errors = attempt(raw)
        if result is not None:
            return result

        attempts += 1
        repair = render_prompt("repair", raw_output=raw, errors="\n".join(f"- {e}" for e in errors),
                               schema=schema)
        raw = llm.invoke(repair).content
        result, errors = attempt(raw)
        if result is not None:
            return result
        return NodeError(node=node, message=f"model output is not a valid {model.__name__} after repair",
                         attempts=attempts, validation_errors=errors, raw_output=raw)
    except Exception as exc:  # LLM/transport failure, e.g. Ollama not running
        return NodeError(node=node, message=f"LLM call failed: {type(exc).__name__}: {exc}",
                         attempts=attempts, raw_output=raw)
