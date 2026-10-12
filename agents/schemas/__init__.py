"""Pydantic schemas shared by all agent nodes. Reference: docs/SCHEMAS.md."""

from agents.schemas.agent_state import FactoryStatus, FixRecord, GameFactoryState, HumanDecision, LoopStep
from agents.schemas.game_spec import Control, GameIdea, GameSpec, Scene
from agents.schemas.node_error import NodeError
from agents.schemas.review_result import ReviewCheck, ReviewResult
from agents.schemas.task_plan import FileChange, FileChangeSet, ImplementationTask, TaskPlan
from agents.schemas.test_result import CommandResult, TestFailure, TestResult

__all__ = [
    "CommandResult",
    "Control",
    "FactoryStatus",
    "FileChange",
    "FileChangeSet",
    "FixRecord",
    "GameFactoryState",
    "GameIdea",
    "GameSpec",
    "HumanDecision",
    "ImplementationTask",
    "LoopStep",
    "NodeError",
    "ReviewCheck",
    "ReviewResult",
    "Scene",
    "TaskPlan",
    "TestFailure",
    "TestResult",
]
