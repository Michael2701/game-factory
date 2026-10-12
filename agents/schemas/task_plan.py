"""Task plan (task decomposer, M5) and proposed file changes (coder M8 / fixer M15)."""

from pathlib import PurePosixPath
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from agents.schemas.game_spec import SLUG_PATTERN, StrictModel

TaskKind = Literal["setup", "config", "code", "test_hooks", "tests", "build", "run_tests"]


class ImplementationTask(StrictModel):
    id: str = Field(min_length=1, description="Short unique id, e.g. 'T1'")
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    kind: TaskKind
    target_files: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    acceptance: str = Field(min_length=1, description="How to tell the task is done")


class TaskPlan(StrictModel):
    game_slug: str = Field(pattern=SLUG_PATTERN)
    tasks: list[ImplementationTask] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_order(self) -> "TaskPlan":
        seen: set[str] = set()
        for task in self.tasks:
            if task.id in seen:
                raise ValueError(f"duplicate task id: {task.id}")
            missing = [dep for dep in task.depends_on if dep not in seen]
            if missing:
                raise ValueError(f"task {task.id} depends on {missing}, which are not earlier tasks")
            seen.add(task.id)
        return self


class FileChange(StrictModel):
    # File content and patches are whitespace-sensitive: never strip them.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    path: str = Field(min_length=1, description="Path relative to the target project root")
    operation: Literal["create", "update", "delete"]
    content: str | None = None
    patch: str | None = None
    reason: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        # Basic sanity only; the real path guard lives in agents/tools (M6).
        value = value.strip()
        if not value:
            raise ValueError("path must not be empty")
        if value.startswith(("/", "~", "\\")) or ":" in value:
            raise ValueError(f"path must be relative: {value}")
        if ".." in PurePosixPath(value.replace("\\", "/")).parts:
            raise ValueError(f"path must not contain '..': {value}")
        return value

    @model_validator(mode="after")
    def _check_payload(self) -> "FileChange":
        has_content, has_patch = self.content is not None, self.patch is not None
        if self.operation == "delete" and (has_content or has_patch):
            raise ValueError("delete must not carry content or patch")
        if self.operation != "delete" and has_content == has_patch:
            raise ValueError(f"{self.operation} needs exactly one of content or patch")
        return self


class FileChangeSet(StrictModel):
    """Output of file-proposing nodes (coder M8, test writer M11, fixer M15): {"changes": [...]}."""

    changes: list[FileChange] = Field(default_factory=list)
