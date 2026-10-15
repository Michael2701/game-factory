"""M21b run log: node events from the graph, LLM call files (prompt / reasoning / reply / repair), viewer."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agents import game_factory_graph as gfg  # noqa: E402
from agents.llm import invoke_structured  # noqa: E402
from agents.run_log import RunLog, active, current, new_run_id, run_dir  # noqa: E402
from agents.schemas import GameSpec  # noqa: E402
from fakes import FakeLLM  # noqa: E402
from scripts import show_run  # noqa: E402
from test_graph import ALL_REPLIES, BAD, SPEC_JSON  # noqa: E402


class ThinkingLLM(FakeLLM):
    """FakeLLM whose replies carry reasoning, like ChatOllama(reasoning=True) with qwen3."""

    def invoke(self, prompt):
        message = super().invoke(prompt)
        return AIMessage(content=message.content, additional_kwargs={"reasoning_content": "I think: keep it small."})


def events(log: RunLog) -> list[dict]:
    return [json.loads(line) for line in (log.dir / "events.jsonl").read_text().splitlines()]


class RunLogTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.log = RunLog(run_dir(self.root, "r1"))

    def test_run_ids(self):
        self.assertRegex(new_run_id("Block Dodger r11"), r"^\d{8}-\d{6}-block-dodger-r11$")
        for bad in ("../x", "a/b", "", ".hidden", "a..b"):
            with self.assertRaises(ValueError, msg=bad):
                run_dir(self.root, bad)

    def test_llm_call_file_and_repair(self):
        with active(self.log):
            result = invoke_structured(ThinkingLLM(BAD, SPEC_JSON), "planner", "PROMPT", GameSpec, {})
        self.assertIsInstance(result, GameSpec)
        first, repair = sorted((self.log.dir / "llm").iterdir())
        self.assertEqual([first.name, repair.name], ["001-planner.md", "002-planner.md"])
        text = first.read_text()
        for part in ("· invalid", "## Errors", "slug: Field required", "I think: keep it small.", BAD, "PROMPT"):
            self.assertIn(part, text)
        self.assertIn("repair attempt", repair.read_text())
        llm = [e for e in events(self.log) if e["kind"] == "llm"]
        self.assertEqual([(e["attempt"], e["ok"]) for e in llm], [(1, False), (2, True)])
        self.assertIn("(repair)", (self.log.dir / "run.log").read_text())

    def test_transport_failure_is_logged(self):
        with active(self.log):
            invoke_structured(FakeLLM(ConnectionError("ollama down")), "planner", "P", GameSpec, {})
        self.assertIn("ollama down", (self.log.dir / "llm/001-planner.md").read_text())

    def test_no_active_log_writes_nothing(self):
        self.assertIsNone(current())
        invoke_structured(FakeLLM(SPEC_JSON), "planner", "P", GameSpec, {})
        self.assertEqual(list((self.log.dir / "llm").iterdir()), [])


class GraphRunLogTest(unittest.TestCase):
    def test_dry_run_logs_every_node_and_llm_call(self):
        root = Path(tempfile.mkdtemp())
        lines = []
        log = gfg.open_run_log(root, "dry", "dry", "fake", "idea", echo=lines.append)
        state = gfg.run("A dodge game.", llm=FakeLLM(*ALL_REPLIES), log=log)
        self.assertEqual(state.status.value, "changes_proposed")  # same result as without a log
        kinds = [(e["kind"], e.get("node")) for e in events(log)]
        nodes = [n for k, n in kinds if k == "node"]
        self.assertEqual(nodes, ["planner", "task_decomposer", "coder_dry_run", "test_writer_dry_run"])
        self.assertEqual(kinds[0][0], "start")
        self.assertEqual(kinds[-1][0], "end")
        self.assertEqual(len(list((log.dir / "llm").iterdir())), len(ALL_REPLIES))  # contextvar reached every node
        timeline = "\n".join(lines)
        self.assertIn('spec "Block Dodger"', timeline)
        self.assertIn("tasks:", timeline)
        self.assertIn("END   status changes_proposed", timeline)

    def test_viewer(self):
        root = Path(tempfile.mkdtemp())
        log = gfg.open_run_log(root, "v1", "v", "fake", "idea")
        with active(log):
            invoke_structured(FakeLLM(SPEC_JSON), "planner", "PROMPT", GameSpec, {})
        log.event("end", status="error", error=None, duration_s=1.0)

        def show(*argv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = show_run.main(["show_run.py", *argv], root=root, follow_seconds=1)
            return code, out.getvalue()

        self.assertEqual(show(), (0, "v1\n"))
        code, out = show("latest", "--follow")
        self.assertEqual(code, 0)
        self.assertIn("START run v1", out)
        self.assertIn("PROMPT", show("v1", "--llm", "1")[1])
        self.assertEqual(show("v1", "--llm", "9")[0], 2)
        self.assertEqual(show("../etc")[0], 2)


if __name__ == "__main__":
    unittest.main()
