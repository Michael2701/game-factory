"""Shared LLM helpers for agent nodes: model factory and JSON output parsing.

Reference: docs/NODES.md.
"""

import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from agents.run_log import current as current_run_log
from agents.schemas.node_error import NodeError

MODEL = "qwen3:30b-a3b"  # fallback when neither the environment nor .env names a model
MODEL_ENV = "GAME_FACTORY_MODEL"  # M21: e.g. GAME_FACTORY_MODEL=qwen3:30b-a3b
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"  # M21b: git-ignored, see .env.example
TEMPERATURE = 0.2
# M21b: hard limits per LLM call. qwen3 once "thought" for 54k tokens / 26 min without ending (r11 fixer).
# Reasoning tokens count towards num_predict; normal calls use 3-9k tokens. A cut-off reply fails the
# attempt (and is logged as such) instead of hanging the run.
MAX_TOKENS = 16384
CALL_TIMEOUT_S = 900

M = TypeVar("M", bound=BaseModel)

FENCED = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)
THINK = re.compile(r"<think>.*?</think>", re.S)  # M21b: qwen3 reasoning, if it ever reaches the content
# A backslash (after an even run of escaped backslashes) followed by a char JSON cannot escape.
INVALID_ESCAPE = re.compile(r'(?<!\\)((?:\\\\)*)\\([^"\\/bfnrtu])')


def read_env_file(path: Path | None = None) -> dict[str, str]:
    """`KEY=value` lines of a .env file (default ENV_FILE; comments, blanks, quotes allowed); {} when missing."""
    path = path or ENV_FILE
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def model_name(model: str | None = None, env_file: Path | None = None) -> str:
    """Explicit model, else $GAME_FACTORY_MODEL, else GAME_FACTORY_MODEL in .env, else MODEL."""
    return model or os.environ.get(MODEL_ENV) or read_env_file(env_file).get(MODEL_ENV) or MODEL


def make_llm(model: str | None = None, temperature: float = TEMPERATURE):
    from langchain_ollama import ChatOllama

    # reasoning=True (M21b): a thinking model (qwen3) returns its reasoning separately in
    # additional_kwargs["reasoning_content"] and a clean `content`; the run log keeps the reasoning.
    return ChatOllama(model=model_name(model), temperature=temperature, reasoning=True,
                      num_predict=MAX_TOKENS, client_kwargs={"timeout": CALL_TIMEOUT_S})


def hit_token_limit(message) -> bool:
    """The reply was cut off at num_predict (Ollama done_reason 'length')."""
    return (getattr(message, "response_metadata", None) or {}).get("done_reason") == "length"


def reasoning_of(message) -> str:
    """The model's thinking from an LLM reply message ('' when the model/fake returns none)."""
    return str((getattr(message, "additional_kwargs", None) or {}).get("reasoning_content") or "")


def fix_invalid_escapes(text: str) -> str:
    """Keep the backslash of escapes that JSON does not know: `\\'` -> `\\\\'`.

    qwen writes JS/TS code into JSON strings with JS escapes such as `\\'` (in 'don\\'t')
    or regex `\\d`, which are invalid JSON. Escaping the backslash yields exactly the code
    the model meant (`\\'` is an apostrophe in any JS string). Valid JSON is unchanged.
    """
    return INVALID_ESCAPE.sub(r"\1\\\\\2", text)


def extract_json(text: str) -> str:
    """Return the JSON object text from an LLM reply.

    Handles the common qwen habits: ```json fences, prose before/after the object, a qwen3
    `<think>` block and JS-style escapes that are invalid in JSON (`fix_invalid_escapes`).
    Raises ValueError when no JSON object can be found.
    """
    text = fix_invalid_escapes(THINK.sub("", text).strip())
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
    normalize: Callable[[M], M] | None = None,
) -> "M | NodeError":
    """Call the LLM and return a validated `model`, or a NodeError. Never raises.

    invoke -> parse (-> deterministic `normalize`, M20) (+ semantic `check`, which returns
    error strings) -> on errors one repair call with the `repair` prompt -> parse/check
    again -> NodeError if still bad. With an active run log (M21b) every call is recorded:
    prompt, reasoning, reply, errors, duration.
    """
    from agents.prompts import render_prompt

    def attempt(raw: str) -> tuple[M | None, list[str]]:
        try:
            result = parse_model(raw, model)
        except ValueError as exc:  # includes ValidationError and JSON errors
            return None, format_errors(exc)
        if normalize:
            result = normalize(result)
        problems = check(result) if check else []
        return (None, problems) if problems else (result, [])

    log = current_run_log()
    attempts, raw, text, started = 0, None, prompt, time.monotonic()

    def call(text: str) -> tuple[str, M | None, list[str]]:
        nonlocal started
        started = time.monotonic()
        message = llm.invoke(text)
        elapsed = time.monotonic() - started
        reply = message.content
        result, errors = attempt(reply)
        if result is None and hit_token_limit(message):
            errors = [f"the reply was cut off at the token limit ({MAX_TOKENS} tokens, reasoning included): "
                      "think less and answer with the JSON directly", *errors]
        if log:
            log.llm_call(node, attempts, text, reply, reasoning_of(message), errors, elapsed)
        return reply, result, errors

    try:
        attempts += 1
        raw, result, errors = call(prompt)
        if result is not None:
            return result

        attempts += 1
        text = render_prompt("repair", raw_output=raw, errors="\n".join(f"- {e}" for e in errors),
                             schema=schema)
        raw, result, errors = call(text)
        if result is not None:
            return result
        return NodeError(node=node, message=f"model output is not a valid {model.__name__} after repair",
                         attempts=attempts, validation_errors=errors, raw_output=raw)
    except Exception as exc:  # LLM/transport failure, e.g. Ollama not running
        message = f"LLM call failed: {type(exc).__name__}: {exc}"
        if log:
            log.llm_call(node, attempts, text, None, "", [message], time.monotonic() - started)
        return NodeError(node=node, message=message, attempts=attempts, raw_output=raw)
