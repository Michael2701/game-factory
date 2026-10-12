import json
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.llm import extract_json  # noqa: E402
from agents.prompts import PROMPT_NAMES, format_files, load_prompt, prompt_variables, render_prompt  # noqa: E402
from agents.schemas import FileChange, FileChangeSet, GameSpec, ReviewResult, TaskPlan, TestResult  # noqa: E402
from agents.schemas.examples import (  # noqa: E402
    BLOCK_DODGER_IDEA,
    sample_file_change,
    sample_game_spec,
    sample_review_result,
    sample_task_plan,
    sample_test_result,
)


SECTIONS = ["## Role", "## Input", "## Rules", "## Output format", "## Example output"]

EXPECTED_VARIABLES = {
    "planner": {"idea", "schema"},
    "task_decomposer": {"game_spec", "project_base", "schema"},
    "coder": {"task", "game_spec", "allowed_paths", "optional_paths", "locked_paths", "existing_files", "schema"},
    "test_writer": {"game_spec", "project_files", "schema"},
    "fixer": {"test_result", "project_tree", "relevant_files", "new_files", "game_spec", "task_plan", "fix_attempt",
              "max_fix_attempts", "previous_attempts", "schema"},
    "reviewer": {"game_spec", "files_summary", "test_result", "facts", "schema"},
    "repair": {"raw_output", "errors", "schema"},
}

# Model each prompt's example output (and real output) must validate against.
OUTPUT_MODEL = {
    "planner": GameSpec,
    "task_decomposer": TaskPlan,
    "coder": FileChangeSet,
    "test_writer": FileChangeSet,
    "fixer": FileChangeSet,
    "reviewer": ReviewResult,
    "repair": None,  # generic: example is only checked to be JSON
}

# Model whose JSON schema is injected as {{schema}}.
SCHEMA_MODEL = {**OUTPUT_MODEL, "repair": GameSpec}

REVIEW_CHECKS = ["scope_small", "testable", "test_hooks_present", "browser_game_suitable",
                 "no_obvious_ux_issues", "files_organized"]


def sample_variables(name: str) -> dict:
    spec, plan = sample_game_spec(), sample_task_plan()
    failed = TestResult(status="failed", failures=[{"name": "build", "message": "TS2307"}])
    files = {"src/main.ts": sample_file_change().content}
    values = {
        "idea": BLOCK_DODGER_IDEA,
        "schema": SCHEMA_MODEL[name].model_json_schema(),
        "game_spec": spec,
        "task": plan.tasks[2],
        "allowed_paths": ["index.html", "src/main.ts"],
        "optional_paths": ["src/main.ts"],
        "locked_paths": ["package.json", "index.html"],
        "project_base": "The project starts from the Phaser + Vite template.",
        "existing_files": files,
        "project_files": files,
        "relevant_files": files,
        "new_files": ["playwright.config.ts"],
        "project_tree": ["index.html", "src/main.ts"],
        "task_plan": plan,
        "test_result": failed if name == "fixer" else sample_test_result(),
        "files_summary": ["index.html", "src/main.ts", "src/scenes/GameScene.ts"],
        "facts": {"build_ok": True, "test_hooks_present": True},
        "fix_attempt": 1,
        "previous_attempts": ["#1 fix proposed: x [src/main.ts]"],
        "max_fix_attempts": 5,
        "raw_output": '{"title": "Snake"}',
        "errors": "- slug: Field required",
    }
    return {k: values[k] for k in EXPECTED_VARIABLES[name]}


def example_json(name: str) -> str:
    example = load_prompt(name).split("## Example output", 1)[1]
    match = re.search(r"```json\n(.*?)\n```", example, re.S)
    assert match, f"{name}: no ```json block in Example output"
    return match.group(1)


class PromptFilesTest(unittest.TestCase):
    def test_all_prompts_exist_with_sections(self):
        for name in PROMPT_NAMES:
            text = load_prompt(name)
            for section in SECTIONS:
                with self.subTest(prompt=name, section=section):
                    self.assertIn(section, text)

    def test_json_only_output_required(self):
        for name in PROMPT_NAMES:
            with self.subTest(prompt=name):
                self.assertIn("Return ONLY one JSON object", load_prompt(name))
                self.assertIn("no extra fields", load_prompt(name))

    def test_placeholders_match_expected(self):
        for name in PROMPT_NAMES:
            with self.subTest(prompt=name):
                self.assertEqual(prompt_variables(name), EXPECTED_VARIABLES[name])

    def test_examples_validate_against_models(self):
        for name in PROMPT_NAMES:
            with self.subTest(prompt=name):
                model = OUTPUT_MODEL[name]
                if model is None:
                    json.loads(example_json(name))
                else:
                    model.model_validate_json(example_json(name))

    def test_reviewer_example_uses_required_checks(self):
        review = ReviewResult.model_validate_json(example_json("reviewer"))
        self.assertEqual([c.name for c in review.checks], REVIEW_CHECKS)
        for check in REVIEW_CHECKS:
            self.assertIn(f"`{check}`", load_prompt("reviewer"))

    def test_safety_rules_in_file_writing_prompts(self):
        for name in ["coder", "test_writer", "fixer"]:
            text = load_prompt(name)
            with self.subTest(prompt=name):
                self.assertIn('Never use absolute paths, "~", or ".."', text)
                self.assertIn("shell commands", text)
                self.assertIn("secrets", text)
                self.assertIn("do not write files yourself", text.lower())

    def test_test_writer_requires_deterministic_hooks(self):
        text = load_prompt("test_writer")
        for needle in ["window.__GAME_STATE__", "window.__TEST_API__", "waitForTimeout", "tests/game.spec.ts"]:
            self.assertIn(needle, text)


class RenderTest(unittest.TestCase):
    def test_render_all_with_samples(self):
        for name in PROMPT_NAMES:
            with self.subTest(prompt=name):
                text = render_prompt(name, **sample_variables(name))
                self.assertNotIn("{{", text)
                schema = json.dumps(SCHEMA_MODEL[name].model_json_schema(), indent=2)
                self.assertIn(schema, text)

    def test_render_serializes_models(self):
        text = render_prompt("task_decomposer", game_spec=sample_game_spec(), project_base="B", schema="S")
        self.assertIn('"slug": "block-dodger"', text)

    def test_missing_variable_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing=\\['schema'\\]"):
            render_prompt("planner", idea="x")

    def test_unknown_variable_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown=\\['extra'\\]"):
            render_prompt("planner", idea="x", schema="s", extra="y")

    def test_format_files(self):
        self.assertEqual(format_files({}), "(none)")
        text = format_files({"a.ts": "line1\n  line2\n", "b.json": "{}"})
        self.assertIn("=== a.ts ===\nline1\n  line2\n=== end of a.ts ===", text)
        self.assertIn("=== b.json ===\n{}\n=== end of b.json ===", text)
        self.assertNotIn("```", text)

    def test_unknown_prompt_rejected(self):
        with self.assertRaises(ValueError):
            load_prompt("../secrets")


@unittest.skipUnless(os.environ.get("RUN_OLLAMA_TESTS") == "1", "set RUN_OLLAMA_TESTS=1 (needs `ollama serve`)")
class PlannerPromptLLMTest(unittest.TestCase):
    def test_planner_prompt_yields_valid_game_spec(self):
        from langchain_ollama import ChatOllama

        llm = ChatOllama(model="qwen2.5-coder:14b", temperature=0.2)
        prompt = render_prompt("planner", **sample_variables("planner"))
        reply = llm.invoke(prompt).content
        spec = GameSpec.model_validate_json(extract_json(reply))
        self.assertEqual(spec.engine, "phaser")
        self.assertTrue(spec.test_requirements)


if __name__ == "__main__":
    unittest.main()
