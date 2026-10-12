import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))  # shared helpers (fakes.py) when run as a single module

from agents.llm import extract_json, parse_model  # noqa: E402
from agents.nodes.planner import plan_game, planner_node  # noqa: E402
from agents.schemas import FactoryStatus, GameFactoryState, GameSpec, NodeError  # noqa: E402
from agents.schemas.examples import BLOCK_DODGER_IDEA, sample_game_spec  # noqa: E402
from fakes import FakeLLM  # noqa: E402

VALID = sample_game_spec().model_dump_json()
INVALID = json.dumps({**sample_game_spec().model_dump(), "slug": "Block Dodger", "difficulty": "hard"})


class ExtractJsonTest(unittest.TestCase):
    def test_variants(self):
        cases = {
            '{"a": 1}': '{"a": 1}',
            '```json\n{"a": 1}\n```': '{"a": 1}',
            '```\n{"a": 1}\n```': '{"a": 1}',
            'Here is the spec:\n{"a": {"b": "}"}}\nHope it helps!': '{"a": {"b": "}"}}',
            'Sure!\n```json\n{"a": 1}\n```\nDone.': '{"a": 1}',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(json.loads(extract_json(text)), json.loads(expected))

    def test_no_json(self):
        with self.assertRaises(ValueError):
            extract_json("I cannot do that.")

    def test_js_escapes_keep_their_backslash(self):
        # qwen writes JS code with \' or regex \d into JSON strings (invalid JSON escapes).
        cases = {
            '{"c": "test(\'player\\\'s turn\')"}': r"test('player\'s turn')",
            r'{"c": "/\d+/"}': r"/\d+/",
            r'{"c": "a\\\'b"}': "a\\\\'b",                         # escaped backslash, then \'
            'Here:\n```json\n{"c": "it\\\'s"}\n```': r"it\'s",     # fenced + prose
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(json.loads(extract_json(text))["c"], expected)

    def test_valid_escapes_unchanged(self):
        text = r'{"c": "a\nb\t\"q\" \\ \/ é \\\\d"}'
        self.assertEqual(extract_json(text), text)
        self.assertEqual(json.loads(extract_json(text))["c"], 'a\nb\t"q" \\ / é \\\\d')

    def test_parse_model(self):
        self.assertEqual(parse_model(f"```json\n{VALID}\n```", GameSpec), sample_game_spec())


class PlanGameTest(unittest.TestCase):
    def test_valid_first_try(self):
        llm = FakeLLM(VALID)
        self.assertEqual(plan_game(BLOCK_DODGER_IDEA, llm=llm), sample_game_spec())
        self.assertEqual(len(llm.prompts), 1)
        self.assertIn(BLOCK_DODGER_IDEA, llm.prompts[0])

    def test_fenced_and_prose(self):
        for reply in [f"```json\n{VALID}\n```", f"Here you go:\n{VALID}\nEnjoy!"]:
            with self.subTest(reply=reply[:20]):
                self.assertIsInstance(plan_game(BLOCK_DODGER_IDEA, llm=FakeLLM(reply)), GameSpec)

    def test_repair_succeeds(self):
        llm = FakeLLM(INVALID, VALID)
        result = plan_game(BLOCK_DODGER_IDEA, llm=llm)
        self.assertEqual(result, sample_game_spec())
        self.assertEqual(len(llm.prompts), 2)
        repair = llm.prompts[1]
        self.assertIn("# Repair", repair)
        self.assertIn("slug: String should match pattern", repair)
        self.assertIn("difficulty: Extra inputs are not permitted", repair)
        self.assertIn('"difficulty": "hard"', repair)  # previous output is included

    def test_not_json_then_repaired(self):
        result = plan_game(BLOCK_DODGER_IDEA, llm=FakeLLM("I think a dodging game is fun.", VALID))
        self.assertIsInstance(result, GameSpec)

    def test_repair_fails(self):
        result = plan_game(BLOCK_DODGER_IDEA, llm=FakeLLM(INVALID, INVALID))
        self.assertIsInstance(result, NodeError)
        self.assertEqual((result.node, result.attempts), ("planner", 2))
        self.assertIn("after repair", result.message)
        self.assertTrue(any("slug" in e for e in result.validation_errors))
        self.assertEqual(result.raw_output, INVALID)

    def test_llm_exception(self):
        result = plan_game(BLOCK_DODGER_IDEA, llm=FakeLLM(ConnectionError("connection refused")))
        self.assertIsInstance(result, NodeError)
        self.assertIn("ConnectionError: connection refused", result.message)
        self.assertEqual(result.attempts, 1)

    def test_invalid_idea_no_llm_call(self):
        llm = FakeLLM()
        result = plan_game("  a ", llm=llm)
        self.assertIsInstance(result, NodeError)
        self.assertEqual(result.message, "invalid game idea")
        self.assertEqual(llm.prompts, [])


class PlannerNodeTest(unittest.TestCase):
    def test_success_update(self):
        update = planner_node(GameFactoryState(user_idea=BLOCK_DODGER_IDEA), llm=FakeLLM(VALID))
        self.assertEqual(update["status"], FactoryStatus.PLANNED)
        self.assertEqual(update["game_spec"], sample_game_spec())

    def test_error_update(self):
        update = planner_node(GameFactoryState(user_idea=BLOCK_DODGER_IDEA), llm=FakeLLM(INVALID, INVALID))
        self.assertEqual(update["status"], FactoryStatus.ERROR)
        self.assertTrue(update["error"].startswith("planner: "))
        NodeError.model_validate_json(update["error"].removeprefix("planner: "))

    def test_in_state_graph(self):
        from langgraph.graph import END, START, StateGraph

        llm = FakeLLM(VALID)
        graph = StateGraph(GameFactoryState)
        graph.add_node("planner", lambda state: planner_node(state, llm=llm))
        graph.add_edge(START, "planner")
        graph.add_edge("planner", END)
        out = graph.compile().invoke({"user_idea": BLOCK_DODGER_IDEA})
        self.assertEqual(out["status"], FactoryStatus.PLANNED)
        self.assertEqual(out["game_spec"], sample_game_spec())


class RunnerTest(unittest.TestCase):
    def test_usage_without_args(self):
        proc = subprocess.run([sys.executable, "scripts/run_planner.py"], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Usage", proc.stderr)

    def test_invalid_idea_exit_1(self):
        proc = subprocess.run([sys.executable, "scripts/run_planner.py", "x"], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(NodeError.model_validate_json(proc.stdout).message, "invalid game idea")

    @unittest.skipUnless(os.environ.get("RUN_OLLAMA_TESTS") == "1", "set RUN_OLLAMA_TESTS=1 (needs `ollama serve`)")
    def test_done_when_command(self):
        proc = subprocess.run([sys.executable, "scripts/run_planner.py", BLOCK_DODGER_IDEA], cwd=ROOT,
                              capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr[-2000:])
        spec = GameSpec.model_validate_json(proc.stdout)
        self.assertEqual(spec.engine, "phaser")


if __name__ == "__main__":
    unittest.main()
