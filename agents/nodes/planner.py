"""Planner node (M4): short game idea -> validated GameSpec.

Flow: validate idea -> planner prompt -> LLM -> parse GameSpec
      -> on invalid output: one repair prompt -> parse again
      -> still invalid / LLM unavailable: NodeError (never raises).
Reference: docs/NODES.md.
"""

from pydantic import ValidationError

from agents.llm import format_errors, invoke_structured, make_llm
from agents.prompts import render_prompt
from agents.schemas import FactoryStatus, GameFactoryState, GameIdea, GameSpec, NodeError

NODE = "planner"


def plan_game(idea: str, llm=None) -> GameSpec | NodeError:
    try:
        idea = GameIdea(text=idea).text
    except ValidationError as exc:
        return NodeError(node=NODE, message="invalid game idea", validation_errors=format_errors(exc))

    schema = GameSpec.model_json_schema()
    prompt = render_prompt("planner", idea=idea, schema=schema)
    return invoke_structured(llm or make_llm(), NODE, prompt, GameSpec, schema)


def planner_node(state: GameFactoryState, llm=None) -> dict:
    """LangGraph node: returns a partial state update."""
    result = plan_game(state.user_idea, llm=llm)
    if isinstance(result, NodeError):
        return {"status": FactoryStatus.ERROR, "error": f"{NODE}: {result.model_dump_json()}"}
    return {"game_spec": result, "status": FactoryStatus.PLANNED, "error": None}
