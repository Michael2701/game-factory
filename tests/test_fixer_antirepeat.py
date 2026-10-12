"""M21 fixer anti-repeat: normalized fingerprints, no-op/whitespace fixes, no-effect lines, widened
relevant files with a budget, trimmed failures, and the loop marking fixes that changed nothing."""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agents import game_factory_graph as gfg  # noqa: E402
from agents.nodes import test_runner  # noqa: E402
from agents.nodes.fixer import (  # noqa: E402
    MAX_FAILURES,
    MAX_STACK_FRAMES,
    _trimmed_failures,
    budget_files,
    check_fix,
    failure_signature,
    fingerprint,
    normalize_lines,
    relevant_files,
)
from agents.schemas import FileChange, FileChangeSet, FixRecord, TestFailure, TestResult  # noqa: E402
from fakes import FakeLLM  # noqa: E402
from test_fix_loop import FakeChecks, TempRoot, reply  # noqa: E402
from test_reviewer import REJECT_BUILD  # noqa: E402

OLD = "const a = 1;\nconst b = 2;\n"


def cs(*items) -> FileChangeSet:
    return FileChangeSet(changes=[FileChange(path=p, operation="update", content=c, reason="r") for p, c in items])


class NormalizeTest(unittest.TestCase):
    def test_lines_and_fingerprint(self):
        self.assertEqual(normalize_lines("  const   a = 1;\n\n// note\n  /* x */\n * y\nfoo( )\n"),
                         ["const a = 1;", "foo( )"])
        a = [FileChange(path="src/x.ts", operation="update", content="const a = 2;\n", reason="r")]
        b = [FileChange(path="src/x.ts", operation="update", content="  const  a = 2; \n// changed\n", reason="x")]
        self.assertEqual(fingerprint(a), fingerprint(b))
        c = [FileChange(path="src/x.ts", operation="update", content="const a = 3;\n", reason="r")]
        self.assertNotEqual(fingerprint(a), fingerprint(c))

    def test_signature_ignores_numbers_and_bundle_names(self):
        def result(msg):
            return TestResult(status="failed", failures=[TestFailure(name="acceptance", message=msg)])
        a = failure_signature(result("Error: ArrowLeft did not move the player: stayed 240\n at index-AB1.js:3:4"))
        b = failure_signature(result("Error: ArrowLeft did not move the player: stayed 233\n at index-ZZ9.js:9:9"))
        self.assertEqual(a, b)
        self.assertNotEqual(a, failure_signature(result("Error: boom")))


class CheckRepeatTest(unittest.TestCase):
    relevant = {"src/x.ts": OLD}

    def test_whitespace_only_change_rejected(self):
        errors = check_fix(cs(("src/x.ts", "const a = 1;\n  const   b = 2;\n// c\n")), self.relevant, [])
        self.assertTrue(any("only whitespace or comments" in e for e in errors), errors)

    def test_seen_fingerprint_rejected(self):
        fix = cs(("src/x.ts", "const a = 5;\nconst b = 2;\n"))
        seen = {fingerprint(fix.changes): 2}
        errors = check_fix(fix, self.relevant, [], seen=seen)
        self.assertEqual(errors, ["changes: the same fix as attempt 2 (ignoring whitespace and comments); it did "
                                  "not solve the failure, so change something else"])

    def test_blocked_lines(self):
        blocked = {"const a = 1;", "const a = 5;"}
        same_lines = cs(("src/x.ts", "const a = 5;\nconst b = 2;\n"))
        self.assertTrue(any("without any effect" in e for e in check_fix(same_lines, self.relevant, [], blocked=blocked)))
        new_line = cs(("src/x.ts", "const a = 1;\nconst b = 3;\n"))
        self.assertEqual(check_fix(new_line, self.relevant, [], blocked=blocked), [])


class WidenAndBudgetTest(unittest.TestCase):
    def test_widen_shows_all_src_and_named_files(self):
        files = {"src/a.ts": "a", "src/scenes/G.ts": "g", "tests/game.spec.ts": "t", "package.json": "{}",
                 "playwright.config.ts": "c"}
        result = TestResult(status="failed", failures=[TestFailure(name="x", message="at src/a.ts:1 tests/game.spec.ts:3")])
        relevant, _ = relevant_files(result, files, widen=True)
        self.assertEqual(sorted(relevant), ["src/a.ts", "src/scenes/G.ts", "tests/game.spec.ts"])

    def test_budget_keeps_priority_order(self):
        files = {"src/big.ts": "x" * 20, "src/named.ts": "y" * 10, "z.json": "z" * 10}
        kept = budget_files(files, ["src/named.ts"], max_chars=25)
        self.assertEqual(list(kept), ["src/named.ts", "z.json"])  # src/big.ts no longer fits, z.json still does
        self.assertEqual(list(budget_files({"huge.ts": "h" * 99}, [], max_chars=10)), ["huge.ts"])  # never empty

    def test_trimmed_failures(self):
        stack = "Error: boom\n" + "\n".join(f"    at f{i} (src/a.ts:{i}:1)" for i in range(20))
        failures = [TestFailure(name="t", message=stack)] * 3 + [TestFailure(name=f"t{i}", message="m") for i in range(9)]
        out = _trimmed_failures(TestResult(status="failed", failures=failures))
        self.assertEqual(len(out), MAX_FAILURES)
        self.assertEqual(out[0]["message"].count("    at "), MAX_STACK_FRAMES)  # duplicates collapsed too
        self.assertEqual([f["name"] for f in out], ["t", "t0", "t1", "t2", "t3"])


class LoopNoEffectTest(TempRoot):
    def test_no_effect_fix_is_marked_and_its_twin_refused(self):
        """Fix A changes nothing -> marked no_effect; its whitespace twin is refused in attempt 2."""
        self.write_case("missing-file")
        main = self.read("src/main.ts")
        fix_a = reply(("src/main.ts", "update", main + "export const attempt = 1;\n"))
        twin = reply(("src/main.ts", "update", main + "export  const attempt = 1;\n// again\n"))
        llm = FakeLLM(fix_a, twin, twin, REJECT_BUILD)
        state, _ = self.loop(llm, checks=FakeChecks("failed"), max_fix_attempts=2)
        self.assertEqual([(s.attempt, s.step, s.status) for s in state.loop_history],
                         [(0, "test", "failed"), (1, "fix", "proposed"), (1, "apply_fix", "applied"),
                          (1, "test", "failed"), (2, "fix", "error")])
        self.assertTrue(state.fix_records[0].no_effect)
        self.assertIn("did NOT change the error", llm.prompts[1])        # attempt 2 is told
        self.assertIn("changes only whitespace or comments", llm.prompts[2])  # the repair prompt names why
        self.assertEqual(state.status.value, "needs_human_review")

    def test_effective_fix_is_not_marked(self):
        self.write_case("two-bugs")
        from test_fix_loop import FIX_MAIN, FIX_GAME_SCENE
        from test_reviewer import APPROVE
        state, _ = self.loop(FakeLLM(FIX_MAIN, FIX_GAME_SCENE, APPROVE))
        self.assertEqual([r.no_effect for r in state.fix_records], [False, False])
        self.assertEqual(len({r.fingerprint for r in state.fix_records}), 2)


if __name__ == "__main__":
    unittest.main()


class HookHintsTest(unittest.TestCase):
    """M21 r7: the hooks lost `result` (renamed hitStatus); the fixer edited GameScene instead."""

    def test_missing_hook_is_named(self):
        from agents.nodes.coder import check_changes, hook_properties
        from agents.nodes.fixer import _failure_view, hook_hints
        hooks = ("(window as any).__GAME_STATE__ = {\n  get scene() { return s; },\n"
                 "  get hitStatus() { return gameScene()?.result ?? null; },\n  get playerX() { return 1; },\n};\n"
                 "(window as any).__TEST_API__ = { startGame() { go(); }, skipTime(seconds: number) { t(); } };\n")
        self.assertNotIn("result", hook_properties(hooks))  # a bare word is not a definition any more
        failed = TestResult(status="failed", failures=[TestFailure(
            name="game.spec.ts › win", message="> 16 | await page.waitForFunction(() => "
                                               "(window as any).__GAME_STATE__.result === 'win');")])
        hints = hook_hints(failed, {"src/testHooks.ts": hooks, "src/main.ts": "x"})
        self.assertEqual(len(hints), 1)
        self.assertIn("reads window.__GAME_STATE__.result, but the hooks in src/testHooks.ts do not define `result`",
                      hints[0])
        self.assertEqual(_failure_view(failed, {"src/testHooks.ts": hooks})["hints"], hints)
        self.assertNotIn("hints", _failure_view(failed, {}))
        # the coder's hook contract now catches it at generation time
        from agents.schemas.examples import sample_template_task_plan
        task = sample_template_task_plan().tasks[1]
        errors = check_changes(cs(("src/testHooks.ts", hooks)), task, {"src/testHooks.ts": "old"})
        self.assertTrue(any("missing ['result']" in e for e in errors), errors)
