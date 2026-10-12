"""Structured failure returned by an agent node instead of raising (M4+)."""

from pydantic import Field

from agents.schemas.game_spec import StrictModel


class NodeError(StrictModel):
    node: str = Field(min_length=1, description="Node name, e.g. 'planner'")
    message: str = Field(min_length=1)
    attempts: int = Field(default=0, ge=0, description="LLM calls made")
    validation_errors: list[str] = Field(default_factory=list)
    raw_output: str | None = Field(default=None, description="Last raw LLM output, if any")
