"""Planner node (M4): short game idea -> validated GameSpec.

Flow: validate idea -> planner prompt -> LLM -> parse GameSpec
      -> on invalid output: one repair prompt -> parse again
      -> still invalid / LLM unavailable: NodeError (never raises).
Reference: docs/NODES.md.
"""

from pydantic import ValidationError

from agents.generators.playtest import check_playtest, normalize_playtest, playtest_of
from agents.llm import format_errors, invoke_structured, make_llm
from agents.prompts import render_prompt
from agents.schemas import FactoryStatus, GameFactoryState, GameIdea, GameSpec, NodeError

NODE = "planner"

# M22: the quality bar of every generated game, added by code (the acceptance test and the reviewer check it).
# M21c: genre-neutral; the difficulty item only for games whose playtest says they get harder.
QUALITY_BAR = (
    "HUD: the game's key value (score, time, moves, lives…) is shown during play and updates as it changes",
    "Visible feedback: important events (hits, pickups, matches, mistakes) give visible feedback "
    "(flash, shake, tween, colour change) and the result screen states win or lose",
    "Start screen: game title, one line explaining the controls, click to start",
    "Restart: a click on the result screen starts a new round without reloading",
    "Distinct colours: what the player controls, what helps and what hurts never share a colour "
    "(src/ui.ts PALETTE: primary, good, danger)",
)
DIFFICULTY_ITEM = "Difficulty grows during a round, exposed as GameScene.difficulty (read via __GAME_STATE__.difficulty)"


def quality_bar(spec: GameSpec) -> tuple[str, ...]:
    return (*QUALITY_BAR, DIFFICULTY_ITEM) if playtest_of(spec).difficulty_ramps else QUALITY_BAR


def with_quality_bar(spec: GameSpec) -> GameSpec:
    extra = [q for q in quality_bar(spec) if q not in spec.quality_requirements]
    return spec.model_copy(update={"quality_requirements": [*spec.quality_requirements, *extra]})


def plan_game(idea: str, llm=None) -> GameSpec | NodeError:
    try:
        idea = GameIdea(text=idea).text
    except ValidationError as exc:
        return NodeError(node=NODE, message="invalid game idea", validation_errors=format_errors(exc))

    schema = GameSpec.model_json_schema()
    prompt = render_prompt("planner", idea=idea, schema=schema)
    return invoke_structured(llm or make_llm(), NODE, prompt, GameSpec, schema,
                             check=check_playtest, normalize=normalize_playtest)


def planner_node(state: GameFactoryState, llm=None) -> dict:
    """LangGraph node: returns a partial state update."""
    result = plan_game(state.user_idea, llm=llm)
    if isinstance(result, NodeError):
        return {"status": FactoryStatus.ERROR, "error": f"{NODE}: {result.model_dump_json()}"}
    return {"game_spec": with_quality_bar(result), "status": FactoryStatus.PLANNED, "error": None}
