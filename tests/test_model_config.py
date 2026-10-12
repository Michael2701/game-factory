"""M21 model configuration: GAME_FACTORY_MODEL and --model (default qwen2.5-coder:14b)."""

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agents import game_factory_graph as gfg  # noqa: E402
from agents.llm import MODEL, MODEL_ENV, make_llm, model_name  # noqa: E402
from fakes import FakeLLM  # noqa: E402
from scripts import run_fix_loop  # noqa: E402
from test_graph import BAD  # noqa: E402


class ModelNameTest(unittest.TestCase):
    def test_precedence(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(MODEL_ENV, None)
            self.assertEqual(model_name(), MODEL)
            self.assertEqual(MODEL, "qwen2.5-coder:14b")
            os.environ[MODEL_ENV] = "qwen2.5-coder:32b"
            self.assertEqual(model_name(), "qwen2.5-coder:32b")
            self.assertEqual(model_name("other:7b"), "other:7b")
            self.assertEqual(make_llm().model, "qwen2.5-coder:32b")  # no network on construction
            self.assertEqual(make_llm("other:7b").model, "other:7b")


class CliModelTest(unittest.TestCase):
    def test_graph_cli_builds_the_llm_from_model(self):
        fake = FakeLLM(BAD, BAD)
        out = io.StringIO()
        with mock.patch.object(gfg, "make_llm", return_value=fake) as make, contextlib.redirect_stdout(out):
            code = gfg.main(["game_factory_graph.py", "a game", "--model", "qwen2.5-coder:32b"])
        make.assert_called_once_with("qwen2.5-coder:32b")
        self.assertEqual(len(fake.prompts), 2)  # the planner used the built model
        self.assertIn("model: qwen2.5-coder:32b", out.getvalue())
        self.assertEqual(code, 1)

    def test_fix_loop_script_has_model_flag(self):
        with mock.patch.object(run_fix_loop, "make_llm") as make, contextlib.redirect_stdout(io.StringIO()):
            run_fix_loop.main(["run_fix_loop.py", "--project-dir", "agents", "--model", "x:1b"])
        make.assert_not_called()  # refused target: nothing built, nothing run


if __name__ == "__main__":
    unittest.main()
