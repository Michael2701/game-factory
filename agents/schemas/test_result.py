"""Command and test results (test runner node, M12)."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from agents.schemas.game_spec import StrictModel


class CommandResult(StrictModel):
    # Keep command output exactly as produced.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    command: str = Field(min_length=1)
    cwd: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_s: float = Field(ge=0)
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class TestFailure(StrictModel):
    __test__ = False  # not a unittest/pytest class

    name: str = Field(min_length=1)
    message: str


class TestResult(StrictModel):
    __test__ = False

    status: Literal["passed", "failed", "error"]
    command_results: list[CommandResult] = Field(default_factory=list)
    failures: list[TestFailure] = Field(default_factory=list)
    summary: str = ""

    @model_validator(mode="after")
    def _passed_has_no_failures(self) -> "TestResult":
        if self.status == "passed" and self.failures:
            raise ValueError("status 'passed' must not list failures")
        return self
