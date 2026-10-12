import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))  # shared helpers (fakes.py) when run as a single module

from agents.generators.phaser_template import DEFAULT_TEMPLATE  # noqa: E402
from agents.nodes.planner import planner_node  # noqa: E402
from agents.nodes.task_decomposer import check_plan, decompose, task_decomposer_node  # noqa: E402
from agents.prompts import load_prompt  # noqa: E402
from agents.schemas import FactoryStatus, GameFactoryState, NodeError, TaskPlan  # noqa: E402
from agents.schemas.examples import BLOCK_DODGER_IDEA, sample_game_spec, sample_task_plan  # noqa: E402
from fakes import FakeLLM  # noqa: E402

SPEC = sample_game_spec()
PLAN = sample_task_plan()
VALID = PLAN.model_dump_json()


def plan_json(tasks: list[dict] | None = None, slug: str = "block-dodger") -> str:
    data = PLAN.model_dump()
    return json.dumps({"game_slug": slug, "tasks": data["tasks"] if tasks is None else tasks})


def tasks_without(kind: str) -> list[dict]:
    kept = [t for t in PLAN.model_dump()["tasks"] if t["kind"] != kind]
    ids = {t["id"] for t in kept}
    return [{**t, "depends_on": [d for d in t["depends_on"] if d in ids]} for t in kept]


def project_snapshot() -> dict[str, str]:
    """Hash of every project file outside .venv/.git/__pycache__ (detects any write)."""
    snap = {}
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if path.is_file() and not {".venv", ".git", "__pycache__", ".idea", "node_modules", "dist"} & set(rel.parts):
            snap[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snap


class CheckPlanTest(unittest.TestCase):
    def test_sample_plan_passes(self):
        self.assertEqual(check_plan(PLAN, SPEC), [])

    def test_prompt_example_passes_for_its_own_spec(self):
        example = load_prompt("task_decomposer").split("```json\n", 1)[1].split("\n```", 1)[0]
        plan = TaskPlan.model_validate_json(example)
        spec = SPEC.model_copy(update={"slug": "target-tapper"})
        self.assertEqual(check_plan(plan, spec, template=DEFAULT_TEMPLATE), [])  # M19: example uses the template

    def test_violations(self):
        tasks = PLAN.model_dump()["tasks"]
        cases = {
            "must be 'block-dodger'": TaskPlan.model_validate_json(plan_json(slug="other-game")),
            "need 5 to 12 tasks": TaskPlan.model_validate_json(plan_json(tasks[:4])),
            "missing task kinds ['build']": TaskPlan.model_validate_json(plan_json(tasks_without("build"))),
            "missing task kinds ['run_tests']": TaskPlan.model_validate_json(plan_json(tasks_without("run_tests"))),
        }
        for needle, plan in cases.items():
            with self.subTest(needle=needle):
                self.assertTrue(any(needle in e for e in check_plan(plan, SPEC)), check_plan(plan, SPEC))

    def test_build_before_code_rejected(self):
        tasks = PLAN.model_dump()["tasks"]
        # T7 (build, deps T3+T4) moved before T5/T6; then an extra code task at the end.
        reordered = tasks[:4] + [tasks[6]] + tasks[4:6] + [tasks[7]] + [
            {"id": "T9", "title": "Polish", "description": "d", "kind": "code", "target_files": [],
             "depends_on": [], "acceptance": "a"}]
        errors = check_plan(TaskPlan.model_validate_json(plan_json(reordered)), SPEC)
        self.assertTrue(any("T7 (build) must come after all 'code' tasks" in e for e in errors), errors)


class DecomposeTest(unittest.TestCase):
    def test_valid_first_try(self):
        llm = FakeLLM(f"```json\n{VALID}\n```")
        self.assertEqual(decompose(SPEC, llm=llm), PLAN)
        self.assertEqual(len(llm.prompts), 1)
        self.assertIn('"slug": "block-dodger"', llm.prompts[0])

    def test_semantic_error_repaired(self):
        llm = FakeLLM(plan_json(tasks_without("run_tests")), VALID)
        self.assertEqual(decompose(SPEC, llm=llm), PLAN)
        self.assertEqual(len(llm.prompts), 2)
        self.assertIn("missing task kinds ['run_tests']", llm.prompts[1])

    def test_slug_mismatch_repaired(self):
        llm = FakeLLM(plan_json(slug="dodger"), VALID)
        self.assertEqual(decompose(SPEC, llm=llm), PLAN)
        self.assertIn("game_slug: must be 'block-dodger'", llm.prompts[1])

    def test_schema_error_repaired(self):
        bad = plan_json([{**t, "depends_on": ["T8"]} if t["id"] == "T2" else t for t in PLAN.model_dump()["tasks"]])
        llm = FakeLLM(bad, VALID)
        self.assertEqual(decompose(SPEC, llm=llm), PLAN)
        self.assertIn("not earlier tasks", llm.prompts[1])

    def test_repair_fails(self):
        bad = plan_json(tasks_without("build"))
        result = decompose(SPEC, llm=FakeLLM(bad, bad))
        self.assertIsInstance(result, NodeError)
        self.assertEqual((result.node, result.attempts), ("task_decomposer", 2))
        self.assertIn("not a valid TaskPlan after repair", result.message)
        self.assertTrue(any("build" in e for e in result.validation_errors))

    def test_llm_exception(self):
        result = decompose(SPEC, llm=FakeLLM(ConnectionError("refused")))
        self.assertIsInstance(result, NodeError)
        self.assertIn("ConnectionError: refused", result.message)

    def test_no_files_written(self):
        before = project_snapshot()
        decompose(SPEC, llm=FakeLLM(VALID))
        decompose(SPEC, llm=FakeLLM("nonsense", "nonsense"))
        self.assertEqual(project_snapshot(), before)


class NodeTest(unittest.TestCase):
    def test_missing_game_spec(self):
        llm = FakeLLM()
        update = task_decomposer_node(GameFactoryState(user_idea=BLOCK_DODGER_IDEA), llm=llm)
        self.assertEqual(update["status"], FactoryStatus.ERROR)
        self.assertIn("run the planner first", update["error"])
        self.assertEqual(llm.prompts, [])

    def test_success_update(self):
        state = GameFactoryState(user_idea=BLOCK_DODGER_IDEA, game_spec=SPEC, status=FactoryStatus.PLANNED)
        update = task_decomposer_node(state, llm=FakeLLM(VALID))
        self.assertEqual(update["status"], FactoryStatus.TASKS_PLANNED)
        self.assertEqual(update["task_plan"], PLAN)

    def test_planner_then_decomposer_graph(self):
        from langgraph.graph import END, START, StateGraph

        llm = FakeLLM(SPEC.model_dump_json(), VALID)
        graph = StateGraph(GameFactoryState)
        graph.add_node("planner", lambda s: planner_node(s, llm=llm))
        graph.add_node("task_decomposer", lambda s: task_decomposer_node(s, llm=llm))
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "task_decomposer")
        graph.add_edge("task_decomposer", END)
        out = graph.compile().invoke({"user_idea": BLOCK_DODGER_IDEA})
        self.assertEqual(out["status"], FactoryStatus.TASKS_PLANNED)
        self.assertEqual(out["task_plan"], PLAN)
        self.assertEqual(len(llm.prompts), 2)


class RunnerTest(unittest.TestCase):
    def run_script(self, *args, timeout=60):
        return subprocess.run([sys.executable, "scripts/run_task_decomposer.py", *args], cwd=ROOT,
                              capture_output=True, text=True, timeout=timeout)

    def test_bad_spec_file(self):
        proc = self.run_script("--spec", "does/not/exist.json")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("bad --spec file", proc.stderr)

    def test_invalid_spec_content(self):
        proc = self.run_script("--spec", "README.md")
        self.assertEqual(proc.returncode, 2)

    @unittest.skipUnless(os.environ.get("RUN_OLLAMA_TESTS") == "1", "set RUN_OLLAMA_TESTS=1 (needs `ollama serve`)")
    def test_done_when_command(self):
        before = project_snapshot()
        proc = self.run_script(timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr[-2000:])
        plan = TaskPlan.model_validate_json(proc.stdout)
        self.assertEqual(check_plan(plan, SPEC), [])
        self.assertEqual(project_snapshot(), before, "task decomposer must not write files")


if __name__ == "__main__":
    unittest.main()
