import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))  # shared helpers (fakes.py) when run as a single module

from agents import game_factory_graph as gfg  # noqa: E402
from agents.schemas import FactoryStatus, GameFactoryState  # noqa: E402
from agents.generators.phaser_template import instantiate  # noqa: E402
from agents.schemas.examples import BLOCK_DODGER_IDEA, sample_game_spec, sample_template_task_plan  # noqa: E402
from agents.tools.filesystem import file_hashes  # noqa: E402
from fakes import FakeLLM  # noqa: E402

SPEC_JSON = sample_game_spec().model_dump_json()
PLAN_JSON = sample_template_task_plan().model_dump_json()  # T1 scenes, T2 test_hooks, T3 tests (M19 template)
BAD = '{"title": "x"}'

TEMPLATE = instantiate("block-dodger", "Block Dodger")  # the coder's starting files (M19)
MAIN_V1 = TEMPLATE["src/main.ts"]
MAIN_V2 = ("import * as Phaser from 'phaser';\nimport { StartScene } from './scenes/StartScene';\n"
           "import { GameScene } from './scenes/GameScene';\nimport { GameOverScene } from './scenes/GameOverScene';\n"
           "import { setupTestHooks } from './testHooks';\n"
           "setupTestHooks(new Phaser.Game({ scene: [StartScene, GameScene, GameOverScene] }));\n")
HOOKS = ("export function setupTestHooks(game: any) {\n"
         "  (window as any).__GAME_STATE__ = { scene: 'StartScene', result: null };\n"
         "  (window as any).__TEST_API__ = { startGame() {}, skipTime(seconds: number) {} };\n}\n")
TESTS_TS = """import { test, expect } from '@playwright/test';
test('a', async ({ page }) => { await page.goto('/'); await page.waitForFunction(() => (window as any).__GAME_STATE__); });
test('b', async ({ page }) => { await page.goto('/'); await page.waitForFunction(() => (window as any).__GAME_STATE__); await page.evaluate(() => (window as any).__TEST_API__.skipTime(60)); });
test('c', async ({ page }) => { await page.goto('/'); expect(1).toBe(1); });
"""


def changes(*items) -> str:
    return json.dumps({"changes": [{"path": p, "operation": op, "content": c, "reason": "r"} for p, op, c in items]})


CODER_REPLIES = [
    changes(("src/scenes/StartScene.ts", "update", "export class StartScene {}\n"),          # T1 (+ main.ts)
            ("src/scenes/GameScene.ts", "update", "export class GameScene {}\n"),
            ("src/scenes/GameOverScene.ts", "create", "export class GameOverScene {}\n"),
            ("src/main.ts", "update", MAIN_V2)),
    changes(("src/testHooks.ts", "update", HOOKS)),                                            # T2
]
TEST_REPLY = changes(("tests/game.spec.ts", "update", TESTS_TS))
ALL_REPLIES = [SPEC_JSON, PLAN_JSON, *CODER_REPLIES, TEST_REPLY]
PROJECT_FILES = sorted({*TEMPLATE, "src/scenes/GameOverScene.ts"})  # template + the one new scene


def run_main(argv, llm, root=None):
    out = io.StringIO()
    kwargs = {"root": root} if root is not None else {}
    with contextlib.redirect_stdout(out):
        code = gfg.main(["game_factory_graph.py", *argv], llm=llm, **kwargs)
    return code, out.getvalue()


def failure_summary(stdout: str) -> str:
    """The `error:` line of a failed CLI run without the (long) raw LLM output, plus the status."""
    lines = []
    for line in stdout.splitlines():
        if line.startswith("error: "):
            node, _, detail = line[len("error: "):].partition(": ")
            try:
                data = json.loads(detail)
                data.pop("raw_output", None)
                detail = json.dumps(data, indent=2)
            except json.JSONDecodeError:
                pass
            lines.append(f"error in {node}: {detail}")
    status = stdout.split("=== STATUS ===\n", 1)[-1].splitlines()[:1]
    return "\n".join([*lines, f"status: {status[0] if status else '?'}", stdout[-1500:]])


def project_tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


class GraphRunTest(unittest.TestCase):
    def test_happy_path(self):
        llm = FakeLLM(*ALL_REPLIES)
        state = gfg.run(BLOCK_DODGER_IDEA, llm=llm)
        self.assertEqual(state.status, FactoryStatus.CHANGES_PROPOSED, state.error)
        self.assertEqual(state.game_spec, sample_game_spec())
        self.assertEqual(state.task_plan, sample_template_task_plan())
        self.assertEqual(state.template, "phaser-vite-template")
        self.assertEqual([c.path for c in state.proposed_changes], [  # only the agents' changes, not the template
            "src/scenes/StartScene.ts", "src/scenes/GameScene.ts", "src/scenes/GameOverScene.ts", "src/main.ts",
            "src/testHooks.ts"])
        self.assertEqual([c.path for c in state.proposed_test_changes], ["tests/game.spec.ts"])
        self.assertEqual(len(llm.prompts), 5)  # planner, decomposer, T1, T2, test writer (T3 belongs to it)
        self.assertEqual([p.split("\n")[0] for p in llm.prompts],
                         ["# Planner", "# Task decomposer", "# Coder", "# Coder", "# Test writer"])

    def test_prompts_carry_the_template(self):
        llm = FakeLLM(*ALL_REPLIES)
        gfg.run(BLOCK_DODGER_IDEA, llm=llm)
        self.assertIn("starts from the Phaser + Vite template", llm.prompts[1])
        self.assertIn('"package.json"', llm.prompts[2].split("Locked template files")[1].split("Existing files")[0])
        self.assertIn("=== package.json ===", llm.prompts[2])                  # template files are context

    def test_scratch_mode_without_template(self):
        llm = FakeLLM(SPEC_JSON, BAD, BAD)
        state = gfg.run(BLOCK_DODGER_IDEA, llm=llm, template=None)
        self.assertIsNone(state.template)
        self.assertIn("The project starts EMPTY", llm.prompts[1])

    def test_coder_sees_previous_files_and_may_update_main(self):
        llm = FakeLLM(*ALL_REPLIES)
        gfg.run(BLOCK_DODGER_IDEA, llm=llm)
        t1_prompt = llm.prompts[2]
        self.assertIn("=== src/main.ts ===\n" + MAIN_V1.rstrip(), t1_prompt)   # the template's main.ts is context
        self.assertIn('MAY also update to integrate your work', t1_prompt)
        self.assertIn('[\n  "src/main.ts"\n]', t1_prompt)                       # optional path offered
        t2_prompt = llm.prompts[3]
        self.assertIn(MAIN_V2.rstrip(), t2_prompt)                               # latest main.ts version

    def test_test_writer_sees_virtual_project(self):
        llm = FakeLLM(*ALL_REPLIES)
        gfg.run(BLOCK_DODGER_IDEA, llm=llm)
        prompt = llm.prompts[4]
        self.assertIn("=== src/testHooks.ts ===\n" + HOOKS.rstrip(), prompt)
        self.assertIn(MAIN_V2.rstrip(), prompt)
        self.assertNotIn(MAIN_V1.rstrip(), prompt)  # merged: only the latest main.ts

    def test_planner_failure_stops(self):
        llm = FakeLLM(BAD, BAD)
        state = gfg.run(BLOCK_DODGER_IDEA, llm=llm)
        self.assertEqual(state.status, FactoryStatus.ERROR)
        self.assertTrue(state.error.startswith("planner: "))
        self.assertEqual(len(llm.prompts), 2)

    def test_decomposer_failure_stops(self):
        llm = FakeLLM(SPEC_JSON, BAD, BAD)
        state = gfg.run(BLOCK_DODGER_IDEA, llm=llm)
        self.assertTrue(state.error.startswith("task_decomposer: "))
        self.assertEqual(state.game_spec, sample_game_spec())
        self.assertEqual(len(llm.prompts), 3)

    def test_coder_failure_keeps_partial_proposals(self):
        llm = FakeLLM(SPEC_JSON, PLAN_JSON, CODER_REPLIES[0], BAD, BAD)  # T2 fails twice
        state = gfg.run(BLOCK_DODGER_IDEA, llm=llm)
        self.assertEqual(state.status, FactoryStatus.ERROR)
        self.assertTrue(state.error.startswith("coder: "))
        self.assertIn("task T2", state.error)
        self.assertEqual(len(state.proposed_changes), 4)
        self.assertEqual(state.proposed_test_changes, [])
        self.assertFalse(any(p.startswith("# Test writer") for p in llm.prompts))

    def test_test_writer_failure(self):
        llm = FakeLLM(*ALL_REPLIES[:-1], BAD, BAD)
        state = gfg.run(BLOCK_DODGER_IDEA, llm=llm)
        self.assertTrue(state.error.startswith("test_writer: "))
        self.assertEqual(len(state.proposed_changes), 5)

    def test_invalid_idea_and_ollama_down(self):
        self.assertEqual(gfg.run("x", llm=FakeLLM()).status, FactoryStatus.ERROR)
        self.assertIn("LLM call failed", gfg.run(BLOCK_DODGER_IDEA, llm=FakeLLM(ConnectionError("refused"))).error)

    def test_no_files_written(self):
        before = file_hashes()
        gfg.run(BLOCK_DODGER_IDEA, llm=FakeLLM(*ALL_REPLIES))
        self.assertEqual(file_hashes(), before)


class GraphStructureTest(unittest.TestCase):
    def test_nodes_and_edges(self):
        g = gfg.build_graph(FakeLLM()).get_graph()
        self.assertEqual(set(g.nodes) - {"__start__", "__end__"}, set(gfg.NODES))
        edges = {(e.source, e.target, e.conditional) for e in g.edges}
        self.assertIn(("__start__", "planner", False), edges)
        for current, following in zip(gfg.NODES, gfg.NODES[1:]):
            self.assertIn((current, following, True), edges)
            self.assertIn((current, "__end__", True), edges)
        self.assertIn(("test_writer_dry_run", "__end__", False), edges)

    def test_apply_graph_adds_apply_node(self):
        g = gfg.build_graph(FakeLLM(), apply=True).get_graph()
        self.assertEqual(set(g.nodes) - {"__start__", "__end__"}, set(gfg.APPLY_NODES))
        edges = {(e.source, e.target, e.conditional) for e in g.edges}
        self.assertIn(("test_writer_dry_run", "apply_changes", True), edges)
        self.assertIn(("test_writer_dry_run", "__end__", True), edges)
        self.assertIn(("apply_changes", "__end__", False), edges)

    def test_import_has_no_side_effects(self):
        with mock.patch("agents.llm.make_llm") as make_llm:
            importlib.reload(gfg)
            make_llm.assert_not_called()


class OutputTest(unittest.TestCase):
    def test_format_state_sections(self):
        state = gfg.run(BLOCK_DODGER_IDEA, llm=FakeLLM(*ALL_REPLIES))
        text = gfg.format_state(state)
        for needle in ["=== GAME SPEC ===", "=== TASK PLAN ===", "=== PROPOSED FILES ===", "CREATE src/scenes/GameOverScene.ts",
                       "UPDATE src/main.ts", "=== PROPOSED TESTS ===", "tests/game.spec.ts", "changes_proposed"]:
            self.assertIn(needle, text)
        self.assertNotIn("--- src/main.ts ---", text)
        self.assertIn("--- src/testHooks.ts ---\n" + HOOKS.rstrip(), gfg.format_state(state, show_files=True))

    def test_main_ok(self):
        code, out = run_main([], FakeLLM(*ALL_REPLIES))
        self.assertEqual(code, 0, out)
        self.assertIn("filesystem unchanged: yes", out)

    def test_main_json(self):
        code, out = run_main(["A snake game on a small grid.", "--json"], FakeLLM(*ALL_REPLIES))
        self.assertEqual(code, 0)
        state = GameFactoryState.model_validate_json(out)
        self.assertEqual(len(state.proposed_test_changes), 1)

    def test_failure_summary_keeps_error_without_raw_output(self):
        error = json.dumps({"node": "test_writer", "message": "bad", "validation_errors": ["hook x missing"],
                            "raw_output": "R" * 5000})
        text = failure_summary(f"=== STATUS ===\nerror\nerror: test_writer: {error}\n")
        self.assertIn("error in test_writer:", text)
        self.assertIn("hook x missing", text)
        self.assertIn("status: error", text)
        self.assertNotIn('"raw_output"', text.split("status:")[0])

    def test_main_error_exit_code(self):
        code, out = run_main([BLOCK_DODGER_IDEA], FakeLLM(BAD, BAD))
        self.assertEqual(code, 1)
        self.assertIn("error: planner:", out)


class ApplyFlowTest(unittest.TestCase):
    """--apply against a temporary project root (never touches the real generated/)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        for d in ("generated", "games", "templates", "agents"):
            (self.root / d).mkdir()
        (self.root / "agents/keep.py").write_text("# untouched\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_run_apply_writes_final_project(self):
        state = gfg.run(BLOCK_DODGER_IDEA, llm=FakeLLM(*ALL_REPLIES), apply=True, root=self.root)
        self.assertEqual(state.status, FactoryStatus.CHANGES_APPLIED, state.error)
        self.assertEqual(state.target_dir, "generated/block-dodger")
        target = self.root / "generated/block-dodger"
        self.assertEqual(project_tree(target), PROJECT_FILES)  # template + agents' files, one write each
        self.assertEqual((target / "src/main.ts").read_text(), MAIN_V2)
        self.assertEqual((target / "playwright.config.ts").read_text(), TEMPLATE["playwright.config.ts"])
        self.assertIn('"name": "block-dodger"', (target / "package.json").read_text())
        self.assertIn("<title>Block Dodger</title>", (target / "index.html").read_text())
        self.assertEqual((target / "tests/game.spec.ts").read_text(), TESTS_TS)
        self.assertEqual(sorted(state.changed_files), [f"generated/block-dodger/{p}" for p in project_tree(target)])

    def test_run_without_apply_writes_nothing(self):
        before = file_hashes(self.root)
        state = gfg.run(BLOCK_DODGER_IDEA, llm=FakeLLM(*ALL_REPLIES), root=self.root)
        self.assertEqual(state.status, FactoryStatus.CHANGES_PROPOSED)
        self.assertEqual(file_hashes(self.root), before)

    def test_upstream_error_skips_apply(self):
        state = gfg.run(BLOCK_DODGER_IDEA, llm=FakeLLM(*ALL_REPLIES[:-1], BAD, BAD), apply=True, root=self.root)
        self.assertTrue(state.error.startswith("test_writer: "))
        self.assertEqual(state.changed_files, [])
        self.assertEqual(project_tree(self.root), ["agents/keep.py"])

    def test_main_apply_ok(self):
        code, out = run_main(["--apply"], FakeLLM(*ALL_REPLIES), root=self.root)
        self.assertEqual(code, 0, out)
        for needle in ["=== APPLIED → generated/block-dodger ===", "WROTE  generated/block-dodger/src/main.ts",
                       "changes_applied", f"files changed inside generated/block-dodger/: {len(PROJECT_FILES)}",
                       "files changed outside it: 0"]:
            self.assertIn(needle, out)

    def test_main_apply_custom_target(self):
        code, out = run_main(["--apply", "--target-dir", "games/dodger"], FakeLLM(*ALL_REPLIES), root=self.root)
        self.assertEqual(code, 0, out)
        self.assertTrue((self.root / "games/dodger/src/testHooks.ts").is_file())

    def test_main_dry_run_hint(self):
        code, out = run_main([], FakeLLM(*ALL_REPLIES), root=self.root)
        self.assertEqual(code, 0, out)
        self.assertIn("filesystem unchanged: yes", out)
        self.assertIn("re-run with --apply to write the project to generated/block-dodger/", out)
        self.assertEqual(project_tree(self.root), ["agents/keep.py"])

    def test_main_bad_target_refused_before_llm(self):
        (self.root / "games/full").mkdir()
        (self.root / "games/full/x.txt").write_text("x")
        for bad in ["templates/x", "agents/x", "generated", "../x", "games/full"]:
            with self.subTest(target=bad):
                llm = FakeLLM()
                code, out = run_main(["--apply", "--target-dir", bad], llm, root=self.root)
                self.assertEqual(code, 2, out)
                self.assertIn("target refused", out)
                self.assertEqual(llm.prompts, [])
        self.assertEqual(project_tree(self.root), ["agents/keep.py", "games/full/x.txt"])

    def test_main_existing_default_target_refused(self):
        (self.root / "generated/block-dodger").mkdir()
        (self.root / "generated/block-dodger/old.txt").write_text("old")
        code, out = run_main(["--apply"], FakeLLM(*ALL_REPLIES), root=self.root)
        self.assertEqual(code, 2, out)
        self.assertIn("error: applier: target refused", out)
        self.assertEqual(project_tree(self.root), ["agents/keep.py", "generated/block-dodger/old.txt"])

    def test_main_target_dir_requires_apply(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            run_main(["--target-dir", "generated/x"], FakeLLM(), root=self.root)


@unittest.skipUnless(os.environ.get("RUN_OLLAMA_TESTS") == "1", "set RUN_OLLAMA_TESTS=1 (needs `ollama serve`)")
class GraphLLMTest(unittest.TestCase):
    def test_done_when_command(self):
        before = file_hashes()
        proc = subprocess.run([sys.executable, "agents/game_factory_graph.py"], cwd=ROOT,
                              capture_output=True, text=True, timeout=1200)
        self.assertEqual(proc.returncode, 0, failure_summary(proc.stdout) + proc.stderr[-2000:])
        for section in ["=== PROPOSED FILES ===", "=== PROPOSED TESTS ===", "changes_proposed",
                        "filesystem unchanged: yes"]:
            self.assertIn(section, proc.stdout)
        self.assertEqual(file_hashes(), before)


if __name__ == "__main__":
    unittest.main()
