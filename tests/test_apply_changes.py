import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))  # shared helpers when run as a single module

from agents.nodes.coder import code_task  # noqa: E402
from agents.schemas import FileChange, FileChangeSet  # noqa: E402
from agents.schemas.examples import sample_game_spec, sample_task_plan  # noqa: E402
from agents.tools.apply_changes import apply_changes  # noqa: E402
from fakes import FakeLLM  # noqa: E402
from test_task_decomposer import project_snapshot  # noqa: E402

TARGET = "generated/game"


def fc(path, content="x\n", operation="create"):
    return FileChange(path=path, operation=operation, content=content if operation != "delete" else None,
                      reason="test")


def forged(path, operation="create", content="x\n", patch=None):
    return FileChange.model_construct(path=path, operation=operation, content=content, patch=patch, reason="forged")


class Sandbox(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        for d in ["generated/game/src", "games", "templates", "agents", ".git"]:
            (self.root / d).mkdir(parents=True)
        (self.root / "generated/game/index.html").write_text("<html></html>\n")
        os.symlink("/etc", self.root / "generated/game/etc-link")

    def tearDown(self):
        self._tmp.cleanup()

    def tree(self) -> dict[str, str]:
        return {p.relative_to(self.root).as_posix(): p.read_text()
                for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()}

    def apply(self, changes, target=TARGET, apply=False):
        return apply_changes(changes, target, apply=apply, root=self.root)


class DryRunAndApplyTest(Sandbox):
    def test_dry_run_writes_nothing(self):
        before = self.tree()
        result = self.apply([fc("src/main.ts", "a\n"), fc("index.html", "<b/>", "update")])
        self.assertTrue(result.ok, result.errors)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.changed_files, [])
        self.assertEqual(self.tree(), before)
        self.assertEqual([(p.path, p.operation, p.bytes, p.old_bytes) for p in result.planned], [
            ("generated/game/src/main.ts", "create", 2, None),
            ("generated/game/index.html", "update", 4, 14),
        ])

    def test_apply_create_update_delete(self):
        (self.root / "generated/game/old.ts").write_text("old")
        result = self.apply([fc("src/main.ts", "a\n"), fc("index.html", "<b/>\n", "update"), fc("old.ts", operation="delete")],
                            apply=True)
        self.assertTrue(result.ok, result.errors)
        self.assertFalse(result.dry_run)
        self.assertEqual(result.changed_files, ["generated/game/src/main.ts", "generated/game/index.html",
                                                "generated/game/old.ts"])
        tree = self.tree()
        self.assertEqual(tree["generated/game/src/main.ts"], "a\n")
        self.assertEqual(tree["generated/game/index.html"], "<b/>\n")
        self.assertNotIn("generated/game/old.ts", tree)

    def test_new_target_folder_and_nested_dirs(self):
        result = self.apply([fc("src/scenes/GameScene.ts")], target="games/new-game", apply=True)
        self.assertTrue(result.ok, result.errors)
        self.assertTrue((self.root / "games/new-game/src/scenes/GameScene.ts").is_file())

    def test_whitespace_preserved(self):
        self.apply([fc("src/a.ts", "  indented\n\n")], apply=True)
        self.assertEqual((self.root / "generated/game/src/a.ts").read_text(), "  indented\n\n")

    def test_empty_set_is_noop(self):
        result = self.apply(FileChangeSet(changes=[]), apply=True)
        self.assertTrue(result.ok)
        self.assertEqual((result.planned, result.changed_files), ([], []))

    def test_summary(self):
        dry = self.apply([fc("src/main.ts", "abc"), fc("index.html", "<b/>", "update")]).summary()
        self.assertIn("DRY RUN · generated/game · 2 change(s)", dry)
        self.assertIn("CREATE  generated/game/src/main.ts  3 B", dry)
        self.assertIn("UPDATE  generated/game/index.html", dry)
        self.assertIn("(was 14 B)", dry)
        bad = self.apply([fc("index.html")]).summary()
        self.assertIn("REJECTED", bad)
        self.assertIn("nothing written", bad)


class RejectionTest(Sandbox):
    def assert_rejected(self, changes, needle, target=TARGET):
        before = self.tree()
        result = self.apply(changes, target=target, apply=True)
        self.assertFalse(result.ok)
        self.assertEqual(result.changed_files, [])
        self.assertEqual(self.tree(), before, "nothing may be written when rejected")
        self.assertTrue(any(needle in e for e in result.errors), result.errors)

    def test_paths(self):
        cases = {
            "outside the project": [forged("../../../x.txt")],
            "outside the project: /tmp": [forged("/tmp/x.txt")],
            "path is protected": [fc(".env", "S=1")],
            "etc-link/evil: path is outside": [fc("etc-link/evil")],
            "is a directory": [fc("src")],
        }
        for needle, changes in cases.items():
            with self.subTest(needle=needle):
                self.assert_rejected(changes, needle)

    def test_escape_target_folder_inside_write_root(self):
        self.assert_rejected([forged("../other-game/x.ts")], "outside the target folder")

    def test_target_dir_rules(self):
        cases = {"generated": "writing is only allowed below", "agents/x": "writing is only allowed below",
                 "/tmp/x": "outside the project", "../x": "outside the project",
                 "generated/game/index.html": "not a directory", ".git/x": "protected"}
        for target, needle in cases.items():
            with self.subTest(target=target):
                self.assert_rejected([fc("a.ts")], needle, target=target)

    def test_operations(self):
        self.assert_rejected([fc("index.html")], "already exists (use update)")
        self.assert_rejected([fc("missing.ts", "x", "update")], "update, but the file does not exist")
        self.assert_rejected([fc("missing.ts", operation="delete")], "delete, but the file does not exist")
        self.assert_rejected([fc("a.ts"), fc("a.ts")], "duplicate change")

    def test_patch_not_supported(self):
        self.assert_rejected([FileChange(path="index.html", operation="update", patch="@@ -1 +1 @@", reason="r")],
                             "patch is not supported")

    def test_size_limit(self):
        self.assert_rejected([fc("big.txt", "x" * 1_000_001)], "larger than")

    def test_package_json(self):
        cases = {
            "not valid JSON": "{oops",
            "scripts.build 'node evil.js'": json.dumps({"scripts": {"build": "node evil.js"}}),
            "scripts.prebuild is not allowed": json.dumps({"scripts": {"build": "vite build", "prebuild": "x"}}),
            "scripts.postbuild is not allowed": json.dumps({"scripts": {"postbuild": "x"}}),
        }
        for needle, content in cases.items():
            with self.subTest(needle=needle):
                self.assert_rejected([fc("package.json", content)], needle)
        ok = self.apply([fc("package.json", json.dumps({"scripts": {"build": "vite build", "dev": "vite"}}))])
        self.assertTrue(ok.ok, ok.errors)

    def test_atomic(self):
        self.assert_rejected([fc("good.ts"), fc("index.html")], "already exists")


class IntegrationTest(Sandbox):
    def test_coder_output_applied(self):
        """M8 -> M9: coder proposes (FakeLLM), applier previews and writes into the sandbox."""
        spec, task = sample_game_spec(), sample_task_plan().tasks[2]  # T3
        reply = json.dumps({"changes": [
            {"path": "index.html", "operation": "create", "content": "<html></html>\n", "reason": "T3"},
            {"path": "src/main.ts", "operation": "create", "content": "import * as Phaser from 'phaser';\n", "reason": "T3"},
        ]})
        proposed = code_task(task, spec, llm=FakeLLM(reply))
        target = "generated/block-dodger"
        preview = self.apply(proposed, target=target)
        self.assertTrue(preview.ok, preview.errors)
        self.assertFalse((self.root / target).exists())
        applied = self.apply(proposed, target=target, apply=True)
        self.assertEqual(applied.changed_files, [f"{target}/index.html", f"{target}/src/main.ts"])
        self.assertEqual((self.root / target / "src/main.ts").read_text(), "import * as Phaser from 'phaser';\n")

    def test_real_project_untouched(self):
        before = project_snapshot()
        apply_changes([fc("src/main.ts")], "generated/should-not-exist")  # dry run against the real root
        self.assertEqual(project_snapshot(), before)
        self.assertFalse((ROOT / "generated/should-not-exist").exists())


class ScriptTest(unittest.TestCase):
    def test_test_apply_changes_script(self):
        proc = subprocess.run([sys.executable, "scripts/test_apply_changes.py"], cwd=ROOT,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("FAIL", proc.stdout)


if __name__ == "__main__":
    unittest.main()
