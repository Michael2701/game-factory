import subprocess
import sys
import unittest
from pathlib import Path

from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.schemas import (  # noqa: E402
    CommandResult,
    FactoryStatus,
    FileChange,
    GameFactoryState,
    GameSpec,
    TaskPlan,
    TestResult,
)
from agents.schemas.examples import (  # noqa: E402
    ALL_SAMPLES,
    sample_game_spec,
    sample_task_plan,
)


def spec_data(**overrides) -> dict:
    return {**sample_game_spec().model_dump(), **overrides}


def plan_data(tasks: list[dict]) -> dict:
    return {"game_slug": "block-dodger", "tasks": tasks}


def task(id: str, depends_on: list[str] | None = None) -> dict:
    return {"id": id, "title": id, "description": "d", "kind": "code",
            "depends_on": depends_on or [], "acceptance": "a"}


class SamplesTest(unittest.TestCase):
    def test_samples_build_and_round_trip(self):
        for name, build in ALL_SAMPLES.items():
            with self.subTest(model=name):
                obj = build()
                self.assertEqual(type(obj).model_validate_json(obj.model_dump_json()), obj)

    def test_json_schema_generation(self):
        for name, build in ALL_SAMPLES.items():
            with self.subTest(model=name):
                schema = type(build()).model_json_schema()
                self.assertIn("properties", schema)

    def test_validate_schemas_script(self):
        proc = subprocess.run([sys.executable, "scripts/validate_schemas.py"], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("all schemas valid", proc.stdout)


class GameSpecTest(unittest.TestCase):
    def test_bad_slug_rejected(self):
        for slug in ["Block Dodger", "block_dodger", "-block", ""]:
            with self.subTest(slug=slug), self.assertRaises(ValidationError):
                GameSpec.model_validate(spec_data(slug=slug))

    def test_extra_field_rejected(self):
        with self.assertRaises(ValidationError):
            GameSpec.model_validate(spec_data(difficulty="hard"))

    def test_empty_scenes_rejected(self):
        with self.assertRaises(ValidationError):
            GameSpec.model_validate(spec_data(scenes=[]))

    def test_engine_only_phaser(self):
        with self.assertRaises(ValidationError):
            GameSpec.model_validate(spec_data(engine="unity"))


class TaskPlanTest(unittest.TestCase):
    def test_sample_is_ordered(self):
        ids = [t.id for t in sample_task_plan().tasks]
        self.assertEqual(ids, ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"])

    def test_duplicate_ids_rejected(self):
        with self.assertRaisesRegex(ValidationError, "duplicate task id"):
            TaskPlan.model_validate(plan_data([task("T1"), task("T1")]))

    def test_forward_dependency_rejected(self):
        with self.assertRaisesRegex(ValidationError, "not earlier tasks"):
            TaskPlan.model_validate(plan_data([task("T1", ["T2"]), task("T2")]))

    def test_unknown_dependency_rejected(self):
        with self.assertRaisesRegex(ValidationError, "not earlier tasks"):
            TaskPlan.model_validate(plan_data([task("T1", ["T9"])]))

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValidationError):
            TaskPlan.model_validate(plan_data([{**task("T1"), "kind": "deploy"}]))


class FileChangeTest(unittest.TestCase):
    def make(self, **kw) -> FileChange:
        return FileChange.model_validate({"path": "src/main.ts", "operation": "create",
                                          "content": "x", "reason": "r", **kw})

    def test_path_is_trimmed(self):
        self.assertEqual(self.make(path="  src/main.ts \n").path, "src/main.ts")
        with self.assertRaises(ValidationError):
            self.make(path="   ")

    def test_content_whitespace_preserved(self):
        change = self.make(content="  indented\n\n", patch=None)
        self.assertEqual(change.content, "  indented\n\n")
        patch = self.make(operation="update", content=None, patch=" context\n-old\n+new\n")
        self.assertEqual(patch.patch, " context\n-old\n+new\n")

    def test_valid_variants(self):
        self.make()
        self.make(operation="update", content=None, patch="@@ -1 +1 @@")
        self.make(operation="delete", content=None)

    def test_unsafe_paths_rejected(self):
        for path in ["/etc/passwd", "~/.ssh/id_rsa", "../outside.ts", "src/../../x", "C:/x", "\\x"]:
            with self.subTest(path=path), self.assertRaises(ValidationError):
                self.make(path=path)

    def test_payload_rules(self):
        cases = [
            {"operation": "create", "content": None},                 # nothing
            {"operation": "create", "content": "x", "patch": "p"},    # both
            {"operation": "delete", "content": "x"},                  # delete with content
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValidationError):
                self.make(**case)


class ResultsTest(unittest.TestCase):
    def test_command_ok(self):
        base = {"command": "npm run build", "cwd": ".", "duration_s": 1}
        self.assertTrue(CommandResult(exit_code=0, **base).ok)
        self.assertFalse(CommandResult(exit_code=1, **base).ok)
        self.assertFalse(CommandResult(exit_code=0, timed_out=True, **base).ok)

    def test_output_whitespace_preserved(self):
        result = CommandResult(command="x", cwd=".", exit_code=0, stdout="  a\n", stderr="\n", duration_s=0)
        self.assertEqual((result.stdout, result.stderr), ("  a\n", "\n"))

    def test_negative_duration_rejected(self):
        with self.assertRaises(ValidationError):
            CommandResult(command="x", cwd=".", exit_code=0, duration_s=-1)

    def test_passed_with_failures_rejected(self):
        with self.assertRaisesRegex(ValidationError, "must not list failures"):
            TestResult(status="passed", failures=[{"name": "t", "message": "boom"}])

    def test_failed_with_failures_ok(self):
        result = TestResult(status="failed", failures=[{"name": "t", "message": "boom"}])
        self.assertEqual(len(result.failures), 1)


class StateTest(unittest.TestCase):
    def test_defaults(self):
        state = GameFactoryState(user_idea="idea")
        self.assertEqual(state.status, FactoryStatus.NEW)
        self.assertEqual((state.fix_attempts, state.max_fix_attempts), (0, 5))
        self.assertEqual(state.changed_files, [])

    def test_invalid_values_rejected(self):
        for kw in [{"fix_attempts": -1}, {"status": "flying"}, {"user_idea": ""}]:
            with self.subTest(kw=kw), self.assertRaises(ValidationError):
                GameFactoryState.model_validate({"user_idea": "idea", **kw})

    def test_works_as_langgraph_state(self):
        from langgraph.graph import END, START, StateGraph

        def plan(state: GameFactoryState) -> dict:
            return {"game_spec": sample_game_spec(), "status": FactoryStatus.PLANNED}

        graph = StateGraph(GameFactoryState)
        graph.add_node("plan", plan)
        graph.add_edge(START, "plan")
        graph.add_edge("plan", END)
        out = graph.compile().invoke({"user_idea": "idea"})

        final = GameFactoryState.model_validate(
            {k: v.model_dump() if isinstance(v, BaseModel) else v for k, v in out.items()}
        )
        self.assertEqual(final.status, FactoryStatus.PLANNED)
        self.assertEqual(final.game_spec, sample_game_spec())


if __name__ == "__main__":
    unittest.main()
