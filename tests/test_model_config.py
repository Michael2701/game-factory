"""Model configuration: --model > $GAME_FACTORY_MODEL > .env > MODEL (M21, .env in M21b)."""

import contextlib
import io
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
from agents import llm as llm_module  # noqa: E402
from agents.llm import MODEL, MODEL_ENV, extract_json, make_llm, model_name, read_env_file  # noqa: E402
from fakes import FakeLLM  # noqa: E402
from scripts import run_fix_loop  # noqa: E402
from test_graph import BAD  # noqa: E402


class ModelNameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env_file = self.tmp / ".env"
        patcher = mock.patch.object(llm_module, "ENV_FILE", self.env_file)  # never the real .env
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_precedence(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(MODEL_ENV, None)
            self.assertEqual(model_name(), MODEL)
            self.assertEqual(MODEL, "qwen3:30b-a3b")
            self.env_file.write_text(f"# local config\n{MODEL_ENV}=from-file:1b\n")
            self.assertEqual(model_name(), "from-file:1b")
            os.environ[MODEL_ENV] = "qwen2.5-coder:32b"
            self.assertEqual(model_name(), "qwen2.5-coder:32b")
            self.assertEqual(model_name("other:7b"), "other:7b")
            self.assertEqual(make_llm().model, "qwen2.5-coder:32b")  # no network on construction
            self.assertEqual(make_llm("other:7b").model, "other:7b")

    def test_env_file_format(self):
        self.assertEqual(read_env_file(), {})  # missing file
        self.env_file.write_text("\n# comment\nexport A='x y'\nB = \"z\"\nnot a pair\nC=a=b\n")
        self.assertEqual(read_env_file(), {"A": "x y", "B": "z", "C": "a=b"})


class LimitsTest(unittest.TestCase):
    def test_every_call_is_bounded(self):
        llm = make_llm("x:1b")
        self.assertEqual(llm.num_predict, llm_module.MAX_TOKENS)
        self.assertEqual(llm.client_kwargs, {"timeout": llm_module.CALL_TIMEOUT_S})
        self.assertTrue(llm.reasoning)

    def test_cut_off_reply_is_explained_to_the_repair(self):
        from langchain_core.messages import AIMessage
        from agents.schemas import GameSpec
        from test_graph import SPEC_JSON

        class CutOff:
            prompts = []

            def __init__(self):
                self.replies = [AIMessage(content="", response_metadata={"done_reason": "length"}),
                                AIMessage(content=SPEC_JSON)]

            def invoke(self, prompt):
                self.prompts.append(prompt)
                return self.replies.pop(0)

        fake = CutOff()
        result = llm_module.invoke_structured(fake, "planner", "P", GameSpec, {})
        self.assertIsInstance(result, GameSpec)
        self.assertIn("cut off at the token limit", fake.prompts[1])  # the repair prompt says why


class ThinkTest(unittest.TestCase):
    def test_think_block_is_dropped(self):
        self.assertEqual(extract_json('<think>maybe {"a": 0}</think>\n{"a": 2}'), '{"a": 2}')


class CliModelTest(unittest.TestCase):
    def test_graph_cli_builds_the_llm_from_model(self):
        fake = FakeLLM(BAD, BAD)
        out = io.StringIO()
        root = Path(tempfile.mkdtemp())  # the run log (M21b) goes below root/logs/runs, not into the repo
        with mock.patch.object(gfg, "make_llm", return_value=fake) as make, contextlib.redirect_stdout(out):
            code = gfg.main(["game_factory_graph.py", "a game", "--model", "qwen2.5-coder:32b"], root=root)
        make.assert_called_once_with("qwen2.5-coder:32b")
        self.assertEqual(len(fake.prompts), 2)  # the planner used the built model
        self.assertIn("model: qwen2.5-coder:32b", out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(len(list((root / "logs/runs").glob("*/llm/*-planner.md"))), 2)  # first + repair

    def test_fix_loop_script_has_model_flag(self):
        with mock.patch.object(run_fix_loop, "make_llm") as make, contextlib.redirect_stdout(io.StringIO()):
            run_fix_loop.main(["run_fix_loop.py", "--project-dir", "agents", "--model", "x:1b"])
        make.assert_not_called()  # refused target: nothing built, nothing run


if __name__ == "__main__":
    unittest.main()
