"""M16 fix loop: apply_fix node, loop graph wiring, CLI --fix-loop, scripts/run_fix_loop.py.

Since M17 the loop ends with the reviewer (passed / attempts used up), so the scripted LLM
replies end with a review (`APPROVE`, `REJECT_BUILD`, `NEEDS_CHANGES` from test_reviewer).
Since M18 the human gate follows the review: the final status is `needs_human_review` (whether
the tests passed is in `test_result`) and the state is saved to <target>/.factory/state.json.

The test runner is replaced by `FakeChecks`, which looks at the project ON DISK and fails
while a fixture bug is still there, so the loop is exercised end to end deterministically
(fixer -> apply_fix really writes, the next "test run" sees the change). Gated: the real
loop (npm + Playwright + Ollama) on the two-bugs fixture.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agents import game_factory_graph as gfg  # noqa: E402
from agents.fixtures.broken_projects import BASE_FILES, CASES  # noqa: E402
from agents.nodes import test_runner  # noqa: E402
from agents.nodes.applier import FIX_NODE, apply_fix_node, check_fix_target  # noqa: E402
from agents.schemas import FactoryStatus, FileChange, GameFactoryState, TestResult  # noqa: E402
from agents.schemas.examples import sample_game_spec, sample_task_plan  # noqa: E402
from agents.tools.safety import SafetyError  # noqa: E402
from fakes import FakeLLM  # noqa: E402
from scripts import run_fix_loop  # noqa: E402
from test_graph import ALL_REPLIES, MAIN_V2, run_main  # noqa: E402
from test_reviewer import APPROVE, NEEDS_CHANGES, REJECT_BUILD  # noqa: E402

TARGET = "generated/demo"
FIXED_MAIN = BASE_FILES["src/main.ts"]
FIXED_GAME_SCENE = BASE_FILES["src/scenes/GameScene.ts"]


def reply(*items) -> str:
    return json.dumps({"changes": [{"path": p, "operation": op, "content": c, "reason": f"fix {p}"}
                                   for p, op, c in items]})


FIX_MAIN = reply(("src/main.ts", "update", FIXED_MAIN))
FIX_GAME_SCENE = reply(("src/scenes/GameScene.ts", "update", FIXED_GAME_SCENE))


def fc(path, op, content=None):
    return FileChange(path=path, operation=op, content=content, reason="r")


class FakeChecks:
    """Stands in for run_project_checks: fails with the fixture's result while its bug is on disk."""

    def __init__(self, status_override: str | None = None):
        self.calls: list[str] = []
        self.status_override = status_override

    def __call__(self, project_dir, steps=test_runner.STEPS, root=None):
        self.calls.append(project_dir)
        if self.status_override:
            return TestResult(status=self.status_override, summary=f"forced {self.status_override}")
        main = (Path(root) / project_dir / "src/main.ts").read_text()
        scene = (Path(root) / project_dir / "src/scenes/GameScene.ts").read_text()
        if "'./scenes/PlayScene'" in main:
            return CASES["missing-file"]().test_result
        if "timeLeft < 0" in scene:
            return CASES["win-logic"]().test_result
        return TestResult(status="passed", summary="install ok · build ok · tests 3/3 passed")


class TempRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "generated").mkdir()
        (self.root / "agents").mkdir()
        (self.root / "agents/keep.py").write_text("keep\n")

    def tearDown(self):
        self._tmp.cleanup()

    def write_case(self, name: str, target: str = TARGET) -> None:
        for path, content in CASES[name]().files.items():
            (self.root / target / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / target / path).write_text(content)

    def read(self, path: str) -> str:
        return (self.root / TARGET / path).read_text()

    def state(self, max_fix_attempts: int = 5, target_dir: str | None = TARGET) -> GameFactoryState:
        return GameFactoryState(user_idea="fix demo", game_spec=sample_game_spec(), task_plan=sample_task_plan(),
                                target_dir=target_dir, max_fix_attempts=max_fix_attempts,
                                status=FactoryStatus.CHANGES_APPLIED)

    def loop(self, llm, checks=None, **state_kwargs) -> tuple[GameFactoryState, FakeChecks]:
        checks = checks or FakeChecks()
        with mock.patch.object(test_runner, "run_project_checks", checks):
            return gfg.run_fix_loop(self.state(**state_kwargs), llm=llm, root=self.root), checks


class ApplyFixNodeTest(TempRoot):
    def test_applies_fix_inside_existing_project(self):
        self.write_case("missing-file")
        state = self.state().model_copy(update={"fix_changes": [fc("src/main.ts", "update", FIXED_MAIN)],
                                                "changed_files": [f"{TARGET}/src/main.ts"]})
        out = apply_fix_node(state, root=self.root)
        self.assertEqual(out["status"], FactoryStatus.TESTING)
        self.assertIsNone(out["error"])
        self.assertEqual(out["fix_changes"], [])
        self.assertEqual(out["changed_files"], [f"{TARGET}/src/main.ts"])  # no duplicates
        self.assertEqual(self.read("src/main.ts"), FIXED_MAIN)

    def test_all_or_nothing(self):
        self.write_case("missing-file")
        before = self.read("src/main.ts")
        bad = [fc("src/main.ts", "update", FIXED_MAIN), fc("src/scenes/GameScene.ts", "create", "dup\n")]
        out = apply_fix_node(self.state().model_copy(update={"fix_changes": bad}), root=self.root)
        self.assertEqual(out["status"], FactoryStatus.ERROR)
        self.assertTrue(out["error"].startswith(f"{FIX_NODE}: "), out["error"])
        self.assertEqual(self.read("src/main.ts"), before)

    def test_refusals_write_nothing(self):
        self.write_case("missing-file")
        traversal = FileChange.model_construct(path="../../agents/keep.py", operation="update",
                                               content="pwned\n", reason="r", patch=None)
        cases = {
            "no fix": ({"fix_changes": []}, "no fix to apply"),
            "no target": ({"target_dir": None, "fix_changes": [fc("a.ts", "create", "x")]}, "target refused"),
            "outside apply roots": ({"target_dir": "agents", "fix_changes": [fc("a.ts", "create", "x")]},
                                    "target refused"),
            "generated itself": ({"target_dir": "generated", "fix_changes": [fc("a.ts", "create", "x")]},
                                 "target refused"),
            "missing project": ({"target_dir": "generated/missing", "fix_changes": [fc("a.ts", "create", "x")]},
                                "target refused"),
            "traversal": ({"fix_changes": [traversal]}, "REJECTED"),
        }
        for name, (update, needle) in cases.items():
            with self.subTest(name):
                out = apply_fix_node(self.state().model_copy(update=update), root=self.root)
                self.assertEqual(out["status"], FactoryStatus.ERROR)
                self.assertIn(needle, out["error"])
        self.assertEqual((self.root / "agents/keep.py").read_text(), "keep\n")
        self.assertFalse((self.root / "generated/missing").exists())

    def test_check_fix_target(self):
        self.write_case("missing-file")
        self.assertEqual(check_fix_target(f"{self.root}/{TARGET}", self.root), TARGET)
        with self.assertRaises(SafetyError):
            check_fix_target("generated/../agents", self.root)


class TestRunnerTargetTest(TempRoot):
    def test_uses_target_dir(self):
        checks = FakeChecks("passed")
        with mock.patch.object(test_runner, "run_project_checks", checks):
            out = test_runner.test_runner_node(self.state(), root=self.root)
        self.assertEqual(checks.calls, [TARGET])
        self.assertEqual(out["status"], FactoryStatus.TESTS_PASSED)


class LoopGraphStructureTest(unittest.TestCase):
    def test_fix_loop_graph(self):
        nodes = set(gfg.build_fix_loop_graph(llm=FakeLLM()).get_graph().nodes)
        self.assertEqual(nodes, {"__start__", "__end__", *gfg.LOOP_NODES, *gfg.REVIEW_NODES, *gfg.GATE_NODES})

    def test_full_graph_with_fix_loop(self):
        graph = gfg.build_graph(llm=FakeLLM(), fix_loop=True).get_graph()
        self.assertEqual(set(graph.nodes), {"__start__", "__end__", *gfg.APPLY_NODES, *gfg.LOOP_NODES,
                                            *gfg.REVIEW_NODES, *gfg.GATE_NODES})
        edges = {(e.source, e.target) for e in graph.edges}
        for edge in [("apply_changes", "test_runner"), ("test_runner", "fixer"), ("fixer", "apply_fix"),
                     ("apply_fix", "test_runner"), ("test_runner", "reviewer"), ("test_runner", "__end__"),
                     ("reviewer", "human_gate"), ("reviewer", "__end__"), ("human_gate", "__end__")]:
            self.assertIn(edge, edges)
        self.assertNotIn(("apply_changes", "__end__"), {(e.source, e.target) for e in graph.edges
                                                         if not e.conditional})

    def test_recursion_limit_covers_attempts(self):
        self.assertEqual(gfg.recursion_limit(5), len(gfg.APPLY_NODES) + 1 + 15 + 1 + 1 + 5)
        self.assertGreater(gfg.recursion_limit(20), len(gfg.APPLY_NODES) + 1 + 3 * 20)


class FixLoopTest(TempRoot):
    def steps(self, state):
        return [(s.attempt, s.step, s.status) for s in state.loop_history]

    def test_passing_project_needs_no_fixer(self):
        self.write_case("missing-file")
        (self.root / TARGET / "src/main.ts").write_text(FIXED_MAIN)
        llm = FakeLLM(APPROVE)
        state, checks = self.loop(llm)
        self.assertEqual(state.status, FactoryStatus.NEEDS_HUMAN_REVIEW)
        self.assertEqual(state.test_result.status, "passed")
        self.assertEqual(self.steps(state), [(0, "test", "passed")])
        self.assertEqual(len(llm.prompts), 1)  # only the reviewer
        self.assertEqual(state.review_result.verdict, "approve")
        self.assertIn("tests passed after 0 fix attempt(s)", gfg.format_loop(state)[-1])

    def test_failure_fix_pass(self):
        self.write_case("missing-file")
        llm = FakeLLM(FIX_MAIN, APPROVE)
        state, checks = self.loop(llm)
        self.assertEqual(state.status, FactoryStatus.NEEDS_HUMAN_REVIEW, state.error)
        self.assertEqual(self.steps(state), [(0, "test", "failed"), (1, "fix", "proposed"),
                                             (1, "apply_fix", "applied"), (1, "test", "passed")])
        self.assertEqual(state.loop_history[1].files, ["src/main.ts"])
        self.assertEqual(state.fix_attempts, 1)
        self.assertEqual(state.fix_changes, [])
        self.assertEqual(self.read("src/main.ts"), FIXED_MAIN)
        self.assertIn(f"{TARGET}/src/main.ts", state.changed_files)
        self.assertIn("UNRESOLVED_IMPORT", llm.prompts[0])
        self.assertEqual(checks.calls, [TARGET, TARGET])

    def test_two_bugs_two_rounds(self):
        self.write_case("two-bugs")
        llm = FakeLLM(FIX_MAIN, FIX_GAME_SCENE, APPROVE)
        state, _ = self.loop(llm)
        self.assertEqual(state.status, FactoryStatus.NEEDS_HUMAN_REVIEW, state.error)
        self.assertEqual(state.fix_attempts, 2)
        self.assertEqual([s.status for s in state.loop_history if s.step == "test"], ["failed", "failed", "passed"])
        self.assertIn("surviving 60 seconds wins", llm.prompts[1])  # round 2 sees the NEW failure
        self.assertIn("Fix attempt 2 of 5", llm.prompts[1])
        self.assertEqual(self.read("src/scenes/GameScene.ts"), FIXED_GAME_SCENE)

    def test_attempts_exhausted(self):
        """A fix that does not fix: exactly max attempts, then tests_failed. 8 rounds fit the recursion limit."""
        self.write_case("missing-file")
        broken = CASES["missing-file"]().files["src/main.ts"]
        replies = [reply(("src/main.ts", "update", broken + f"const attempt{i} = {i};\n")) for i in range(1, 9)]
        llm = FakeLLM(*replies, REJECT_BUILD)
        state, checks = self.loop(llm, max_fix_attempts=8)
        self.assertEqual(state.status, FactoryStatus.NEEDS_HUMAN_REVIEW)
        self.assertEqual(state.test_result.status, "failed")
        self.assertEqual(state.fix_attempts, 8)
        self.assertEqual(len(llm.prompts), 9)  # 8 fixes + review
        self.assertEqual(state.review_result.verdict, "reject")
        self.assertEqual(len(checks.calls), 9)
        self.assertEqual(self.steps(state)[-1], (8, "test", "failed"))
        self.assertIn("fix attempts exhausted (8/8)", gfg.format_loop(state)[-1])

    def test_zero_attempts(self):
        self.write_case("missing-file")
        llm = FakeLLM(REJECT_BUILD)
        state, _ = self.loop(llm, max_fix_attempts=0)
        self.assertEqual(state.status, FactoryStatus.NEEDS_HUMAN_REVIEW)
        self.assertEqual(state.test_result.status, "failed")
        self.assertEqual(len(llm.prompts), 1)  # no fixer, only the reviewer
        self.assertEqual(state.review_result.verdict, "reject")

    def test_runner_error_stops(self):
        self.write_case("missing-file")
        llm = FakeLLM()
        state, _ = self.loop(llm, checks=FakeChecks("error"))
        self.assertEqual(state.status, FactoryStatus.ERROR)
        self.assertEqual(self.steps(state), [(0, "test", "error")])
        self.assertEqual(llm.prompts, [])  # no fixer, no reviewer
        self.assertIsNone(state.review_result)
        self.assertFalse((self.root / TARGET / ".factory").exists())  # no gate after an error

    def test_no_safe_fix_costs_an_attempt(self):
        """M20: an attempt without a usable fix does not end the loop; exhausted -> reviewer -> gate."""
        self.write_case("missing-file")
        before = self.read("src/main.ts")
        state, checks = self.loop(FakeLLM('{"changes": []}', '{"changes": []}', REJECT_BUILD), max_fix_attempts=2)
        self.assertEqual(state.status, FactoryStatus.NEEDS_HUMAN_REVIEW, state.error)
        self.assertIsNone(state.error)
        self.assertEqual(self.steps(state), [(0, "test", "failed"), (1, "fix", "error"), (2, "fix", "error")])
        self.assertIn("no safe fix", state.loop_history[1].summary)
        self.assertEqual(self.read("src/main.ts"), before)
        self.assertEqual(len(checks.calls), 1)  # nothing changed, so no re-test
        self.assertEqual(state.review_result.verdict, "reject")
        self.assertIn("fix attempts exhausted (2/2)", gfg.format_loop(state)[-1])

    def test_failed_attempt_then_fix(self):
        self.write_case("missing-file")
        state, checks = self.loop(FakeLLM('{"changes": []}', FIX_MAIN, APPROVE))
        self.assertEqual(state.status, FactoryStatus.NEEDS_HUMAN_REVIEW, state.error)
        self.assertEqual(self.steps(state), [(0, "test", "failed"), (1, "fix", "error"), (2, "fix", "proposed"),
                                             (2, "apply_fix", "applied"), (2, "test", "passed")])
        self.assertTrue(gfg.gate_passed(state))
        self.assertIn("tests passed after 2 fix attempt(s)", gfg.format_loop(state)[-1])

    def test_fixer_node_error_costs_an_attempt(self):
        self.write_case("missing-file")
        bad = reply(("agents/keep.py", "update", "x\n"))
        state, _ = self.loop(FakeLLM(bad, bad, REJECT_BUILD), max_fix_attempts=1)  # attempt + its repair
        self.assertEqual(state.status, FactoryStatus.NEEDS_HUMAN_REVIEW, state.error)
        self.assertEqual(self.steps(state)[-1], (1, "fix", "error"))
        self.assertTrue(state.loop_history[-1].summary.startswith("fixer: "))
        self.assertEqual((self.root / "agents/keep.py").read_text(), "keep\n")

    def test_apply_fix_rejection_costs_an_attempt(self):
        """The fixer allows creating a file the error names; apply_fix still validates on disk."""
        self.write_case("missing-file")
        with mock.patch("agents.nodes.applier.apply_changes") as apply:
            apply.return_value = mock.Mock(ok=False, summary=lambda: "REJECTED · nothing written · boom")
            state, _ = self.loop(FakeLLM(FIX_MAIN, REJECT_BUILD), max_fix_attempts=1)
        self.assertEqual(state.status, FactoryStatus.NEEDS_HUMAN_REVIEW, state.error)
        self.assertEqual(self.steps(state)[-1], (1, "apply_fix", "error"))
        self.assertIn("boom", state.loop_history[-1].summary)
        self.assertEqual(state.fix_changes, [])

    def test_fixer_precondition_error_stays_fatal(self):
        """Errors that are not a failed model attempt (no attempt consumed) still end the loop."""
        state = self.state().model_copy(update={"test_result": TestResult(status="passed", summary="ok")})
        update = gfg._fix_step(state, FakeLLM(), self.root)
        self.assertEqual(update["status"], FactoryStatus.ERROR)
        self.assertEqual(gfg._after_fix_attempt(state.model_copy(update=update)), gfg.END)


class FixLoopCliTest(TempRoot):
    def test_main_fix_loop_end_to_end(self):
        """idea -> ... -> apply_changes -> test (fails) -> fixer -> apply_fix -> test (passes)."""
        def checks(project_dir, steps=test_runner.STEPS, root=None):
            main = (Path(root) / project_dir / "src/main.ts").read_text()
            if "export const fixed = true;" in main:
                return TestResult(status="passed", summary="tests 3/3 passed")
            return CASES["missing-file"]().test_result

        fixed = reply(("src/main.ts", "update", MAIN_V2 + "export const fixed = true;\n"))
        with mock.patch.object(test_runner, "run_project_checks", checks):
            code, out = run_main(["--fix-loop"], FakeLLM(*ALL_REPLIES, fixed, APPROVE), root=self.root)
        self.assertEqual(code, 0, out)
        for needle in ["=== FIX LOOP ===", "#1  apply_fix applied", "tests passed after 1 fix attempt(s)",
                       "=== REVIEW ===", "verdict: approve", "=== HUMAN REVIEW ===", "needs_human_review",
                       "scripts/decide.py --project-dir generated/block-dodger approve",
                       "files changed outside it: 0"]:
            self.assertIn(needle, out)
        self.assertTrue((self.root / "generated/block-dodger/src/main.ts").read_text().endswith("export const fixed = true;\n"))
        self.assertTrue((self.root / "generated/block-dodger/.factory/state.json").is_file())

    def test_main_fix_loop_exhausted_exit_1(self):
        with mock.patch.object(test_runner, "run_project_checks", FakeChecks("failed")):
            code, out = run_main(["--fix-loop", "--max-fix-attempts", "0"], FakeLLM(*ALL_REPLIES, NEEDS_CHANGES),
                                 root=self.root)
        self.assertEqual(code, 1, out)
        self.assertIn("fix attempts exhausted (0/0)", out)
        self.assertIn("approve is not available", out)

    def test_flag_validation(self):
        for argv in (["--max-fix-attempts", "3"], ["--fix-loop", "--max-fix-attempts", "-1"],
                     ["--fix-loop", "--max-fix-attempts", "99"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit), \
                    contextlib.redirect_stderr(io.StringIO()):
                run_main(argv, FakeLLM(), root=self.root)


def run_script(argv, llm, root):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = run_fix_loop.main(["run_fix_loop.py", *argv], llm=llm, root=root)
    return code, out.getvalue()


class ScriptTest(TempRoot):
    def test_case_is_written_and_fixed(self):
        with mock.patch.object(test_runner, "run_project_checks", FakeChecks()):
            code, out = run_script(["--case", "two-bugs"], FakeLLM(FIX_MAIN, FIX_GAME_SCENE, APPROVE), self.root)
        self.assertEqual(code, 0, out)
        for needle in ["generated/fix-demo-two-bugs/ · 8 source files", "tests passed after 2 fix attempt(s)",
                       "-import { GameScene } from './scenes/PlayScene';", "+    if (this.timeLeft === 0) {",
                       "=== REVIEW ===", "verdict: approve", "=== HUMAN REVIEW ===", "status: needs_human_review",
                       "saved state: generated/fix-demo-two-bugs/.factory/state.json", "files changed outside it: 0"]:
            self.assertIn(needle, out)
        self.assertNotIn(".factory", out.split("=== SOURCE CHANGES MADE BY THE LOOP ===")[1].split("===")[0])

    def test_existing_target_refused_before_anything(self):
        (self.root / "generated/fix-demo-missing-file").mkdir()
        (self.root / "generated/fix-demo-missing-file/old.txt").write_text("old")
        llm = FakeLLM()
        code, out = run_script(["--case", "missing-file"], llm, self.root)
        self.assertEqual(code, 2, out)
        self.assertIn("target refused", out)
        self.assertEqual(llm.prompts, [])
        self.assertEqual(sorted(p.name for p in (self.root / "generated/fix-demo-missing-file").iterdir()),
                         ["old.txt"])

    def test_project_dir_outside_refused(self):
        code, out = run_script(["--project-dir", "agents"], FakeLLM(), self.root)
        self.assertEqual(code, 2, out)

    def test_project_dir_loop_and_json(self):
        self.write_case("win-logic")
        with mock.patch.object(test_runner, "run_project_checks", FakeChecks()):
            code, out = run_script(["--project-dir", TARGET, "--json"], FakeLLM(FIX_GAME_SCENE, APPROVE), self.root)
        self.assertEqual(code, 0, out)
        state = GameFactoryState.model_validate_json(out)
        self.assertEqual(state.status, FactoryStatus.NEEDS_HUMAN_REVIEW)
        self.assertEqual(state.fix_attempts, 1)
        self.assertEqual(state.review_result.verdict, "approve")


@unittest.skipUnless(os.environ.get("RUN_NPM_TESTS") == "1", "set RUN_NPM_TESTS=1 (needs network for npm install)")
class RealFixturesTest(TempRoot):
    def test_base_passes_and_real_cases_fail(self):
        """The fixture project really passes; every `fails_for_real` case really fails with its first error."""
        projects = {"base": BASE_FILES, **{n: make().files for n, make in CASES.items() if make().fails_for_real}}
        for name, files in projects.items():
            with self.subTest(case=name):
                target = f"generated/{name}"
                for path, content in files.items():
                    (self.root / target / path).parent.mkdir(parents=True, exist_ok=True)
                    (self.root / target / path).write_text(content)
                result = test_runner.run_project_checks(target, root=self.root)
                if name == "base":
                    self.assertEqual(result.status, "passed", result.summary)
                    continue
                expected = CASES[name]().test_result
                self.assertEqual(result.status, "failed", result.summary)
                self.assertEqual(result.failures[0].name, expected.failures[0].name)


@unittest.skipUnless(os.environ.get("RUN_OLLAMA_TESTS") == "1" and os.environ.get("RUN_NPM_TESTS") == "1",
                     "set RUN_OLLAMA_TESTS=1 RUN_NPM_TESTS=1 (needs `ollama serve` + network for npm install)")
class RealFixLoopTest(TempRoot):
    def test_two_bugs_fixed_by_real_loop(self):
        """Done-when (M16): real build error + real failing Playwright test, fixed by qwen through the loop."""
        code, out = run_script(["--case", "two-bugs"], None, self.root)
        self.assertEqual(code, 0, out)
        self.assertIn("tests passed after", out)
        self.assertIn("=== REVIEW ===", out)
        self.assertIn("status: needs_human_review", out)
        self.assertIn("files changed outside it: 0", out)


if __name__ == "__main__":
    unittest.main()
