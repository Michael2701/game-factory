"""Game idea and structured game specification (produced by the planner node, M4)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class StrictModel(BaseModel):
    """Base for all schemas: unknown keys (e.g. invented by the LLM) are rejected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GameIdea(StrictModel):
    text: str = Field(min_length=3, max_length=500)


class Scene(StrictModel):
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


class Control(StrictModel):
    input: str = Field(min_length=1, description="Key or input, e.g. 'ArrowLeft'")
    action: str = Field(min_length=1, description="What the input does, e.g. 'move left'")


class PlaytestPlayer(StrictModel):
    moves_by_itself: bool = Field(default=False, description="true if the avatar keeps moving without input "
                                                              "(e.g. a snake); then 'no key held' may still move it")


class PlaytestInput(StrictModel):
    input: str = Field(min_length=1, description="One input from `controls`: a key name such as 'ArrowLeft', "
                                                 "'ArrowUp', 'Space', 'KeyW', 'Enter', or 'Click'")
    expect: Literal["player_left", "player_right", "player_up", "player_down", "score_up", "state_changes"] = Field(
        description="What a real press/click must visibly cause: the avatar moves left/right/up/down on screen, "
                    "the score increases, or (for anything else) the game state changes")


class PlaytestRoundEnd(StrictModel):
    by: Literal["timer", "hook"] = Field(description="'timer': the round ends after `seconds` of game time; "
                                                     "'hook': the round has no time limit")
    seconds: int | None = Field(default=None, ge=1, le=600, description="Round length for by='timer'")


class Playtest(StrictModel):
    """How the automatic acceptance test plays THIS game (M21c): a small fixed vocabulary of generic checks."""

    player: PlaytestPlayer | None = Field(default=None, description="The avatar the player controls; null if the "
                                                                    "game has none (clickers, card/puzzle games)")
    inputs: list[PlaytestInput] = Field(min_length=1, description="1-4 inputs a player uses first")
    moves_on_its_own: bool = Field(description="true if objects move without any input (falling, flying, "
                                               "enemies walking)")
    hud: Literal["time", "input", "none"] = Field(description="the on-screen value changes with game time, "
                                                             "with the player's input (score/moves), or not at all")
    difficulty_ramps: bool = Field(description="true if the game gets harder over time during a round")
    round_end: PlaytestRoundEnd


class GameSpec(StrictModel):
    title: str = Field(min_length=1)
    slug: str = Field(pattern=SLUG_PATTERN)
    genre: str = Field(min_length=1)
    engine: Literal["phaser"] = "phaser"
    core_loop: str = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1)
    controls: list[Control] = Field(min_length=1)
    win_condition: str = Field(min_length=1)
    lose_condition: str = Field(min_length=1)
    test_requirements: list[str] = Field(min_length=1)
    asset_requirements: list[str] = Field(default_factory=list)
    sound_requirements: list[str] = Field(default_factory=list)
    # M22: the quality bar every generated game must meet; filled in by the planner node (code), not the LLM
    quality_requirements: list[str] = Field(default_factory=list)
    # M21c: how the acceptance test plays this game (written by the planner, normalized/checked by code)
    playtest: Playtest | None = None
