"""Structured review of a generated game (reviewer node, M17)."""

from typing import Literal

from pydantic import Field

from agents.schemas.game_spec import StrictModel


class ReviewCheck(StrictModel):
    name: str = Field(min_length=1, description="e.g. 'scope_small', 'test_hooks_present'")
    passed: bool
    note: str = ""


class ReviewResult(StrictModel):
    verdict: Literal["approve", "needs_changes", "reject"]
    checks: list[ReviewCheck] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
