"""M18 human approval gate: node, decisions, next actions, saved state, graph stop, scripts/decide.py.

All deterministic (no LLM, no npm): the loop uses FakeChecks + FakeLLM from test_fix_loop.
"""

import contextlib
import io
import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agents import game_factory_graph as gfg  # noqa: E402
from agents.nodes import test_runner  # noqa: E402
from agents.nodes.human_gate import (  # noqa: E402
    STATE_FILE,
    GateError,
    decide,
    format_gate,
    human_gate_node,
    load_state,
    next_actions,
    save_state,
)
from agents.schemas import FactoryStatus, GameFactoryState, ReviewResult, TestResult  # noqa: E402
from agents.tools.filesystem import read_project  # noqa: E402
from agents.tools.safety import SafetyError  # noqa: E402
from fakes import FakeLLM  # noqa: E402
from scripts import decide as decide_script  # noqa: E402
from test_fix_loop import FIX_MAIN, TARGET, FakeChecks, TempRoot  # noqa: E402
from test_reviewer import APPROVE, NEEDS_CHANGES, PASSED, TESTS_FAILED  # noqa: E402

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
STATE_PATH = f"{TARGET}/{STATE_FILE}"


class GateRoot(TempRoot):
    def setUp(self):
        super().setUp()
        self.write_case("missing-file")

    def gated(self, result: TestResult = PASSED, verdict_reply: str = APPROVE, **update) -> GameFactoryState:
        state = self.state().model_copy(update={"test_result": result,
                                                "review_result": ReviewResult.model_validate_json(verdict_reply),
                                                **update})
        out = human_gate_node(state, root=self.root)
        self.assertEqual(out["status"], FactoryStatus.NEEDS_HUMAN_REVIEW, out.get("error"))
        return state.model_copy(update=out)

    def saved(self) -> dict:
        return json.loads((self.root / STATE_PATH).read_text())


class HumanGateNodeTest(GateRoot):
    def test_stops_and_saves_state_inside_project(self):
        state = self.gated()
        self.assertIsNone(state.error)
        saved = self.saved()
        self.assertEqual(saved["status"], "needs_human_review")
        self.assertEqual(saved["review_result"]["verdict"], "approve")
        self.assertEqual(load_state(TARGET, self.root), state)
        self.assertEqual((self.root / "agents/keep.py").read_text(), "keep\n")

    def test_failed_tests_also_reach_the_gate(self):
        self.gated(TESTS_FAILED, NEEDS_CHANGES)
        self.assertEqual(self.saved()["test_result"]["status"], "failed")

    def test_old_decision_is_cleared(self):
        state = decide(self.gated(), "reject", now=NOW)
        out = human_gate_node(state.model_copy(update={"status": FactoryStatus.TESTS_PASSED}), root=self.root)
        self.assertIsNone(out["human_decision"])
        self.assertNotIn("human_decision", self.saved())

    def test_missing_input_or_bad_target_writes_nothing(self):
        review = ReviewResult.model_validate_json(APPROVE)
        cases = {
            "no test_result": ({"review_result": review}, "test_result and review_result"),
            "no review_result": ({"test_result": PASSED}, "test_result and review_result"),
            "no target": ({"test_result": PASSED, "review_result": review, "target_dir": None}, "cannot save"),
            "outside apply roots": ({"test_result": PASSED, "review_result": review, "target_dir": "agents"},
                                    "cannot save"),
            "missing project": ({"test_result": PASSED, "review_result": review, "target_dir": "generated/nope"},
                                "cannot save"),
        }
        for name, (update, needle) in cases.items():
            with self.subTest(name):
                out = human_gate_node(self.state().model_copy(update=update), root=self.root)
                self.assertEqual(out["status"], FactoryStatus.ERROR)
                self.assertTrue(out["error"].startswith("human_gate: "), out["error"])
                self.assertIn(needle, out["error"])
        self.assertFalse((self.root / TARGET / ".factory").exists())
        self.assertFalse((self.root / "agents/.factory").exists())
        self.assertFalse((self.root / "generated/nope").exists())


class DecideTest(GateRoot):
    def test_transitions(self):
        for decision, status in [("approve", FactoryStatus.APPROVED), ("reject", FactoryStatus.REJECTED),
                                 ("needs_changes", FactoryStatus.NEEDS_CHANGES)]:
            with self.subTest(decision):
                state = decide(self.gated(), decision, "a note", now=NOW)
                self.assertEqual(state.status, status)
                self.assertEqual(state.human_decision.decision, decision)
                self.assertEqual(state.human_decision.note, "a note")
                self.assertEqual(state.human_decision.decided_at, "2026-10-12T10:00:00+00:00")
                self.assertEqual(GameFactoryState.model_validate_json(state.model_dump_json()), state)

    def test_approve_needs_passing_tests(self):
        state = self.gated(TESTS_FAILED, NEEDS_CHANGES)
        with self.assertRaisesRegex(GateError, "cannot approve: tests did not pass"):
            decide(state, "approve")
        self.assertEqual(decide(state, "reject").status, FactoryStatus.REJECTED)
        self.assertEqual(decide(state, "needs_changes").status, FactoryStatus.NEEDS_CHANGES)

    def test_forbidden_transitions(self):
        decided = decide(self.gated(), "approve", now=NOW)
        with self.assertRaisesRegex(GateError, r"no decision pending: status is approved \(decided: approve\)"):
            decide(decided, "reject")
        for status in (FactoryStatus.TESTS_PASSED, FactoryStatus.ERROR, FactoryStatus.NEW):
            with self.subTest(status), self.assertRaisesRegex(GateError, "no decision pending"):
                decide(self.state().model_copy(update={"status": status, "test_result": PASSED}), "approve")
        with self.assertRaisesRegex(GateError, "unknown decision"):
            decide(self.gated(), "maybe")


class NextActionsTest(GateRoot):
    def joined(self, state) -> str:
        return "\n".join(next_actions(state))

    def test_needs_human_review(self):
        text = self.joined(self.gated())
        for needle in [f"cd {TARGET} && npm run dev", f"python scripts/decide.py --project-dir {TARGET} approve",
                       f"--project-dir {TARGET} changes --note", f"--project-dir {TARGET} reject"]:
            self.assertIn(needle, text)
        failed = self.joined(self.gated(TESTS_FAILED, NEEDS_CHANGES))
        self.assertIn("approve is not available", failed)
        self.assertNotIn(" approve [", failed)

    def test_per_decision(self):
        cases = {
            "approve": ["npm run build", f"{TARGET}/dist/"],
            "needs_changes": ["requested: add a restart key", f"run_fix_loop.py --project-dir {TARGET}",
                              "not passed to the fixer automatically"],
            "reject": [f"the project stays in {TARGET}/", "--fix-loop"],
        }
        for decision, needles in cases.items():
            with self.subTest(decision):
                text = self.joined(decide(self.gated(), decision, "add a restart key"))
                for needle in needles:
                    self.assertIn(needle, text)

    def test_other_status(self):
        self.assertEqual(next_actions(self.state()), ["no human decision for status changes_applied"])

    def test_format_gate(self):
        lines = format_gate(decide(self.gated(), "needs_changes", "faster", now=NOW))
        text = "\n".join(lines)
        for needle in ["status: needs_changes", "tests: passed", "reviewer verdict: approve",
                       "human decision: needs_changes at 2026-10-12T10:00:00+00:00 · note: faster",
                       f"saved state: {STATE_PATH}", "next actions:"]:
            self.assertIn(needle, text)


class SavedStateTest(GateRoot):
    def test_round_trip(self):
        state = decide(self.gated(), "reject", "no", now=NOW)
        self.assertEqual(save_state(state, self.root), STATE_PATH)
        self.assertEqual(load_state(TARGET, self.root), state)

    def test_load_errors(self):
        with self.assertRaisesRegex(SafetyError, "no saved state"):
            load_state(TARGET, self.root)
        with self.assertRaises(SafetyError):
            load_state("agents", self.root)
        (self.root / TARGET / ".factory").mkdir()
        (self.root / STATE_PATH).write_text('{"status": "approved"}')
        with self.assertRaisesRegex(ValueError, "not a valid GameFactoryState"):
            load_state(TARGET, self.root)

    def test_factory_dir_is_not_project_source(self):
        self.gated()
        self.assertTrue((self.root / STATE_PATH).is_file())
        self.assertFalse([p for p in read_project(TARGET, self.root) if ".factory" in p])


class GraphStopsAtGateTest(GateRoot):
    def test_graph_stops_at_gate(self):
        llm = FakeLLM(FIX_MAIN, APPROVE)
        with mock.patch.object(test_runner, "run_project_checks", FakeChecks()):
            state = gfg.run_fix_loop(self.state(), llm=llm, root=self.root)
        self.assertEqual(state.status, FactoryStatus.NEEDS_HUMAN_REVIEW, state.error)
        self.assertTrue(gfg.gate_passed(state))
        self.assertIsNone(state.human_decision)
        self.assertEqual(len(llm.prompts), 2)  # fixer + reviewer, nothing after the gate
        self.assertEqual(load_state(TARGET, self.root).status, FactoryStatus.NEEDS_HUMAN_REVIEW)
        self.assertEqual(load_state(TARGET, self.root).review_result, state.review_result)
        text = gfg.format_state(state)
        self.assertIn("=== HUMAN REVIEW ===", text)
        self.assertIn("tests passed after 1 fix attempt(s)", text)

    def test_reviewer_error_skips_gate(self):
        with mock.patch.object(test_runner, "run_project_checks", FakeChecks("passed")):
            state = gfg.run_fix_loop(self.state(), llm=FakeLLM(), root=self.root)  # no reply: reviewer fails
        self.assertEqual(state.status, FactoryStatus.ERROR)
        self.assertTrue(state.error.startswith("reviewer: "), state.error)
        self.assertFalse((self.root / TARGET / ".factory").exists())
        self.assertFalse(gfg.gate_passed(state))

    def test_gate_passed_needs_passing_tests(self):
        self.assertFalse(gfg.gate_passed(self.gated(TESTS_FAILED, NEEDS_CHANGES)))
        self.assertFalse(gfg.gate_passed(decide(self.gated(), "approve")))


def run_decide(argv, root):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = decide_script.main(["decide.py", *argv], root=root)
    return code, out.getvalue()


class DecideScriptTest(GateRoot):
    def test_show_then_decide_once(self):
        self.gated()
        code, out = run_decide(["--project-dir", TARGET, "--show"], self.root)
        self.assertEqual(code, 0, out)
        self.assertIn("status: needs_human_review", out)
        self.assertEqual(self.saved()["status"], "needs_human_review")

        code, out = run_decide(["--project-dir", TARGET, "changes", "--note", " add a restart key "], self.root)
        self.assertEqual(code, 0, out)
        self.assertIn(f"saved: {STATE_PATH}", out)
        self.assertIn("requested: add a restart key", out)
        self.assertEqual(self.saved()["status"], "needs_changes")
        self.assertEqual(self.saved()["human_decision"]["note"], "add a restart key")

        before = (self.root / STATE_PATH).read_text()
        code, out = run_decide(["--project-dir", TARGET, "approve"], self.root)
        self.assertEqual(code, 2, out)
        self.assertIn("no decision pending", out)
        self.assertEqual((self.root / STATE_PATH).read_text(), before)

    def test_approve_refused_when_tests_failed(self):
        self.gated(TESTS_FAILED, NEEDS_CHANGES)
        before = (self.root / STATE_PATH).read_text()
        code, out = run_decide(["--project-dir", TARGET, "approve"], self.root)
        self.assertEqual(code, 2, out)
        self.assertIn("cannot approve", out)
        self.assertEqual((self.root / STATE_PATH).read_text(), before)

    def test_approve(self):
        self.gated()
        code, out = run_decide(["--project-dir", TARGET, "approve", "--note", "fun"], self.root)
        self.assertEqual(code, 0, out)
        self.assertIn("status: approved", out)
        self.assertIn("npm run build", out)

    def test_missing_or_invalid_state_exit_1(self):
        code, out = run_decide(["--project-dir", TARGET, "--show"], self.root)
        self.assertEqual(code, 1, out)
        self.assertIn("no saved state", out)
        (self.root / TARGET / ".factory").mkdir()
        (self.root / STATE_PATH).write_text("not json")
        code, out = run_decide(["--project-dir", TARGET, "reject"], self.root)
        self.assertEqual(code, 1, out)
        self.assertEqual((self.root / STATE_PATH).read_text(), "not json")

    def test_bad_project_dir_exit_2(self):
        for target in ("agents", "generated/nope", "../outside"):
            with self.subTest(target):
                code, out = run_decide(["--project-dir", target, "--show"], self.root)
                self.assertEqual(code, 2, out)

    def test_usage_errors(self):
        for argv in ([], ["--project-dir", TARGET], ["--project-dir", TARGET, "approve", "--show"],
                     ["--project-dir", TARGET, "--show", "--note", "x"], ["--project-dir", TARGET, "maybe"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit), \
                    contextlib.redirect_stderr(io.StringIO()):
                run_decide(argv, self.root)


if __name__ == "__main__":
    unittest.main()
