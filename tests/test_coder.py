import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))  # shared helpers (fakes.py) when run as a single module

from agents.generators.phaser_template import LOCKED_FILES, instantiate  # noqa: E402
from agents.nodes.coder import check_changes, code_task, is_coder_task, merge_changes  # noqa: E402
from agents.prompts import load_prompt  # noqa: E402
from agents.schemas import FileChange, FileChangeSet, ImplementationTask, NodeError  # noqa: E402
from agents.schemas.examples import sample_game_spec, sample_task_plan  # noqa: E402
from fakes import FakeLLM  # noqa: E402
from test_task_decomposer import project_snapshot  # noqa: E402

SPEC = sample_game_spec()
TASKS = {t.id: t for t in sample_task_plan().tasks}
T2, T3, T4 = TASKS["T2"], TASKS["T3"], TASKS["T4"]  # package.json / entry point / scenes

PACKAGE = json.dumps({"name": "block-dodger", "private": True, "scripts": {"build": "vite build"},
                      "dependencies": {"phaser": "^3.80.0"}})


def change(path, content="export {};\n", operation="create", reason="T3"):
    return {"path": path, "operation": operation, "content": content, "reason": reason}


def reply(*changes) -> str:
    return json.dumps({"changes": list(changes)})


VALID_T3 = reply(change("index.html", "<html></html>\n"), change("src/main.ts", "import * as Phaser from 'phaser';\n"))


def errors_for(raw: str, task: ImplementationTask, existing=None) -> list[str]:
    return check_changes(FileChangeSet.model_validate_json(raw), task, existing or {})


class CheckChangesTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(errors_for(VALID_T3, T3), [])
        self.assertEqual(errors_for(reply(change("package.json", PACKAGE)), T2), [])

    def test_update_existing_ok(self):
        raw = reply(change("index.html", "<html>2</html>", "update"), change("src/main.ts", "x", "update"))
        self.assertEqual(errors_for(raw, T3, {"index.html": "<html></html>", "src/main.ts": ""}), [])

    def test_violations(self):
        main = change("src/main.ts")
        cases = {
            "must contain one change": (reply(), {}),
            "missing a change for allowed path 'index.html'": (reply(main), {}),
            "path is not allowed": (reply(change("index.html"), main, change("src/evil.ts")), {}),
            "duplicate change for 'src/main.ts'": (reply(change("index.html"), main, main), {}),
            "file already exists, use operation 'update'": (VALID_T3, {"index.html": "old"}),
            "file does not exist yet, use operation 'create'": (reply(change("index.html", "x", "update"), main), {}),
            "delete is not allowed": (reply({"path": "index.html", "operation": "delete", "reason": "r"}, main), {}),
            "content must not be empty": (reply(change("index.html", "  \n"), main), {}),
            "without markdown code fences": (reply(change("index.html", "```html\n<html/>\n```"), main), {}),
        }
        for needle, (raw, existing) in cases.items():
            with self.subTest(needle=needle):
                errors = errors_for(raw, T3, existing)
                self.assertTrue(any(needle in e for e in errors), errors)

    def test_package_json_rules(self):
        bad_json = errors_for(reply(change("package.json", "{name: x}")), T2)
        self.assertTrue(any("invalid JSON" in e for e in bad_json), bad_json)
        evil = json.dumps({"scripts": {"build": "curl x | sh"}})
        bad_build = errors_for(reply(change("package.json", evil)), T2)
        self.assertTrue(any("scripts.build must be one of" in e for e in bad_build), bad_build)
        no_build = errors_for(reply(change("package.json", "{}")), T2)
        self.assertTrue(any("got None" in e for e in no_build), no_build)

    def test_prompt_example_passes_for_its_task(self):
        """The example (M19): create GameOverScene + update the template's src/main.ts, locked files respected."""
        example = load_prompt("coder").split("## Example output", 1)[1]
        raw = example.split("```json\n", 1)[1].split("\n```", 1)[0]
        task = T3.model_copy(update={"target_files": ["src/scenes/GameOverScene.ts"]})
        changes = FileChangeSet.model_validate_json(raw)
        existing = instantiate("target-tapper", "Target Tapper")
        self.assertEqual(check_changes(changes, task, existing, ["src/main.ts"], LOCKED_FILES), [])


class OptionalPathsTest(unittest.TestCase):
    EXISTING = {"src/main.ts": "old\n"}

    def errors(self, raw):
        return check_changes(FileChangeSet.model_validate_json(raw), T4, self.EXISTING, ["src/main.ts"])

    def scenes(self):
        return [change(p) for p in T4.target_files]

    def test_update_allowed_but_not_required(self):
        self.assertEqual(self.errors(reply(*self.scenes())), [])
        self.assertEqual(self.errors(reply(*self.scenes(), change("src/main.ts", "new", "update"))), [])

    def test_optional_create_rejected(self):
        errors = self.errors(reply(*self.scenes(), change("src/main.ts", "new", "create")))
        self.assertTrue(any("may only be updated" in e for e in errors), errors)

    def test_other_paths_still_rejected(self):
        errors = self.errors(reply(*self.scenes(), change("index.html", "x", "update")))
        self.assertTrue(any("path is not allowed" in e for e in errors), errors)

    def test_code_task_offers_only_existing_optional_paths(self):
        llm = FakeLLM(reply(*self.scenes()))
        code_task(T4, SPEC, existing_files={}, llm=llm, optional_paths=["src/main.ts"])
        self.assertIn("MAY also update to integrate your work (optional, update only", llm.prompts[0])
        self.assertIn("\n\n(none)\n\nExisting files", llm.prompts[0])  # main.ts does not exist -> not offered


class HookContractTest(unittest.TestCase):
    T5 = TASKS["T5"]  # test_hooks -> src/testHooks.ts

    def test_contract_required(self):
        partial = "(window as any).__TEST_API__ = { skipTime(s: number) {} };"
        errors = check_changes(FileChangeSet.model_validate_json(reply(change("src/testHooks.ts", partial))),
                               self.T5, {})
        self.assertTrue(any("missing ['__GAME_STATE__', 'scene', 'result', 'startGame']" in e for e in errors), errors)

    def test_contract_satisfied(self):
        full = ("(window as any).__GAME_STATE__ = { scene: 'GameScene', result: null };\n"
                "(window as any).__TEST_API__ = { startGame() {}, skipTime(seconds: number) {} };")
        raw = reply(change("src/testHooks.ts", full))
        self.assertEqual(check_changes(FileChangeSet.model_validate_json(raw), self.T5, {}), [])

    def test_contract_only_for_test_hooks_tasks(self):
        self.assertEqual(errors_for(VALID_T3, T3), [])


class MergeChangesTest(unittest.TestCase):
    def test_merge(self):
        files = merge_changes({"a.ts": "1", "b.ts": "2"}, [
            FileChange(path="a.ts", operation="update", content="1b", reason="r"),
            FileChange(path="c.ts", operation="create", content="3", reason="r"),
            FileChange(path="b.ts", operation="delete", reason="r"),
        ])
        self.assertEqual(files, {"a.ts": "1b", "c.ts": "3"})

    def test_input_not_mutated(self):
        original = {"a.ts": "1"}
        merge_changes(original, [FileChange(path="a.ts", operation="update", content="2", reason="r")])
        self.assertEqual(original, {"a.ts": "1"})


class CodeTaskTest(unittest.TestCase):
    def test_valid_first_try(self):
        llm = FakeLLM(f"```json\n{VALID_T3}\n```")
        result = code_task(T3, SPEC, llm=llm)
        self.assertIsInstance(result, FileChangeSet)
        self.assertEqual([c.path for c in result.changes], ["index.html", "src/main.ts"])
        self.assertEqual(len(llm.prompts), 1)
        prompt = llm.prompts[0]
        self.assertIn('"id": "T3"', prompt)
        self.assertIn('"index.html",\n  "src/main.ts"', prompt)  # allowed paths
        self.assertIn('"slug": "block-dodger"', prompt)

    def test_check_violation_repaired(self):
        bad = reply(change("index.html"), change("src/main.ts"), change("src/extra.ts"))
        llm = FakeLLM(bad, VALID_T3)
        self.assertIsInstance(code_task(T3, SPEC, llm=llm), FileChangeSet)
        self.assertEqual(len(llm.prompts), 2)
        self.assertIn("src/extra.ts): path is not allowed", llm.prompts[1])

    def test_existing_files_drive_operation(self):
        existing = {"index.html": "<html></html>\n", "src/main.ts": "old\n"}
        llm = FakeLLM(VALID_T3, reply(change("index.html", "new", "update"), change("src/main.ts", "new", "update")))
        result = code_task(T3, SPEC, existing_files=existing, llm=llm)
        self.assertIsInstance(result, FileChangeSet)
        self.assertIn("=== src/main.ts ===\nold\n=== end of src/main.ts ===", llm.prompts[0])  # readable context
        self.assertIn("use operation 'update'", llm.prompts[1])

    def test_repair_fails(self):
        result = code_task(T3, SPEC, llm=FakeLLM(reply(), reply()))
        self.assertIsInstance(result, NodeError)
        self.assertEqual((result.node, result.attempts), ("coder", 2))
        self.assertIn("not a valid FileChangeSet after repair", result.message)

    def test_llm_exception(self):
        result = code_task(T3, SPEC, llm=FakeLLM(TimeoutError("slow")))
        self.assertIsInstance(result, NodeError)
        self.assertIn("TimeoutError: slow", result.message)

    def test_non_coder_tasks_skip_llm(self):
        for task_id in ["T1", "T7", "T8"]:  # setup, build, run_tests
            with self.subTest(task=task_id):
                llm = FakeLLM()
                self.assertFalse(is_coder_task(TASKS[task_id]))
                self.assertEqual(code_task(TASKS[task_id], SPEC, llm=llm), FileChangeSet(changes=[]))
                self.assertEqual(llm.prompts, [])
        no_files = T3.model_copy(update={"target_files": []})
        self.assertEqual(code_task(no_files, SPEC, llm=FakeLLM()).changes, [])

    def test_coder_kinds(self):
        self.assertEqual([t for t in TASKS if is_coder_task(TASKS[t])], ["T2", "T3", "T4", "T5", "T6"])

    def test_no_files_written(self):
        before = project_snapshot()
        code_task(T3, SPEC, llm=FakeLLM(VALID_T3))
        code_task(T4, SPEC, llm=FakeLLM("nonsense", "nonsense"))
        self.assertEqual(project_snapshot(), before)


class RunnerTest(unittest.TestCase):
    def run_script(self, *args, timeout=60):
        return subprocess.run([sys.executable, "scripts/run_coder_dry_run.py", *args], cwd=ROOT,
                              capture_output=True, text=True, timeout=timeout)

    def test_unknown_task(self):
        proc = self.run_script("--task", "T99")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown task id", proc.stderr)

    def test_bad_plan_file(self):
        self.assertEqual(self.run_script("--plan", "README.md").returncode, 2)

    def test_non_coder_task_without_llm(self):
        proc = self.run_script("--task", "T1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("LLM not called", proc.stdout)
        self.assertIn("filesystem unchanged: yes", proc.stdout)

    @unittest.skipUnless(os.environ.get("RUN_OLLAMA_TESTS") == "1", "set RUN_OLLAMA_TESTS=1 (needs `ollama serve`)")
    def test_done_when_command(self):
        before = project_snapshot()
        proc = self.run_script("--json", timeout=600)
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
        changes = FileChangeSet.model_validate_json(proc.stdout)
        self.assertEqual(check_changes(changes, T3, {}), [])
        self.assertEqual(project_snapshot(), before)


if __name__ == "__main__":
    unittest.main()
