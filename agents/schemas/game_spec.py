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
