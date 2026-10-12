"""Shared LangGraph state for the game factory graph (used from M7)."""

from enum import StrEnum
from typing import Literal

from pydantic import Field

from agents.schemas.game_spec import GameSpec, StrictModel
from agents.schemas.review_result import ReviewResult
from agents.schemas.task_plan import FileChange, TaskPlan
from agents.schemas.test_result import CommandResult, TestResult


class FactoryStatus(StrEnum):
    NEW = "new"
    PLANNED = "planned"
    TASKS_PLANNED = "tasks_planned"
    CODING = "coding"
    CHANGES_PROPOSED = "changes_proposed"  # dry run finished: code + tests proposed (M13)
    CHANGES_APPLIED = "changes_applied"  # --apply: proposals written to target_dir (M14)
    TESTING = "testing"
    TESTS_FAILED = "tests_failed"
    FIXING = "fixing"
    TESTS_PASSED = "tests_passed"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"
    ERROR = "error"


class LoopStep(StrictModel):
    """One step of the fix loop (M16), recorded by the graph for the report."""

    step: Literal["test", "fix", "apply_fix"]
    attempt: int = Field(ge=0)  # fix attempt the step belongs to; 0 = initial test run
    status: str = Field(min_length=1)  # test: passed/failed/error · fix: proposed/error · apply_fix: applied/error
    summary: str = ""
    files: list[str] = Field(default_factory=list)  # fix: proposed paths · apply_fix: written paths


class HumanDecision(StrictModel):
    """Decision taken by a human at the approval gate (M18), recorded by scripts/decide.py."""

    decision: Literal["approve", "reject", "needs_changes"]
    note: str = ""
    decided_at: str = Field(min_length=1)  # ISO 8601, UTC


class GameFactoryState(StrictModel):
    user_idea: str = Field(min_length=1)
    game_spec: GameSpec | None = None
    task_plan: TaskPlan | None = None
    proposed_changes: list[FileChange] = Field(default_factory=list)  # code, proposed by the coder (M13)
    proposed_test_changes: list[FileChange] = Field(default_factory=list)  # tests, by the test writer (M13)
    template: str | None = None  # project template below templates/ the agents start from (M19); None = empty
    target_dir: str | None = None  # project-relative apply target, e.g. generated/block-dodger (M14)
    changed_files: list[str] = Field(default_factory=list)
    fix_changes: list[FileChange] = Field(default_factory=list)  # latest fix proposed by the fixer (M15)
    command_results: list[CommandResult] = Field(default_factory=list)
    test_result: TestResult | None = None
    review_result: ReviewResult | None = None
    human_decision: HumanDecision | None = None  # set by decide() after the human gate (M18)
    loop_history: list[LoopStep] = Field(default_factory=list)  # test / fix / apply_fix steps (M16)
    fix_attempts: int = Field(default=0, ge=0)
    max_fix_attempts: int = Field(default=5, ge=0)
    status: FactoryStatus = FactoryStatus.NEW
    error: str | None = None
