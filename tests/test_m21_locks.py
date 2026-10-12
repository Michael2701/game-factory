"""M21: locked files for the fixer, click-to-start contract, agent-write manifest + audit script."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agents.generators.phaser_template import LOCKED_FILES, instantiate  # noqa: E402
from agents.nodes.applier import MANIFEST_FILE, apply_fix_node, apply_node  # noqa: E402
from agents.nodes.coder import check_changes  # noqa: E402
from agents.nodes.fixer import check_fix  # noqa: E402
from agents.schemas import FileChange, FileChangeSet  # noqa: E402
from agents.schemas.examples import sample_template_task_plan  # noqa: E402
from scripts import audit_generated  # noqa: E402
from test_applier_node import make_state  # noqa: E402


def change_set(*items) -> FileChangeSet:
    return FileChangeSet(changes=[FileChange(path=p, operation=op, content=c, reason="r") for p, op, c in items])


class FixerLocksTest(unittest.TestCase):
    def test_fixer_rejects_locked_files(self):
        relevant = {"tests/acceptance.spec.ts": "old\n", "src/scenes/GameScene.ts": "a\n"}
        for path in ("tests/acceptance.spec.ts", "tests/fixtures.ts", "vite.config.ts", "playwright.config.ts"):
            with self.subTest(path=path):
                errors = check_fix(change_set((path, "update", "new\n")), {**relevant, path: "old\n"}, [],
                                   LOCKED_FILES)
                self.assertEqual(len(errors), 1, errors)
                self.assertIn("is locked (read-only)", errors[0])
        ok = change_set(("src/scenes/GameScene.ts", "update", "b\n"))
        self.assertEqual(check_fix(ok, relevant, [], LOCKED_FILES), [])


class ClickToStartTest(unittest.TestCase):
    def test_start_scene_must_keep_pointerdown(self):
        task = sample_template_task_plan().tasks[0]
        base = instantiate("b", "B")
        def errors(start: str) -> list[str]:
            return check_changes(change_set(("src/scenes/StartScene.ts", "update", start),
                                            ("src/scenes/GameScene.ts", "update", "x\n"),
                                            ("src/scenes/GameOverScene.ts", "create", "x\n")), task, base)
        self.assertTrue(any("click anywhere" in e for e in errors("this.input.keyboard!.once('keydown-SPACE', f);\n")))
        self.assertEqual(errors("this.input.once('pointerdown', () => this.scene.start('GameScene'));\n"), [])


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "generated").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def audit(self, target="generated/block-dodger"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = audit_generated.main(["audit_generated.py", "--project-dir", target], root=self.root)
        return code, out.getvalue()

    def test_apply_fix_updates_manifest_and_audit_detects_hand_edits(self):
        state = make_state()
        state = state.model_copy(update=apply_node(state, root=self.root))
        code, out = self.audit()
        self.assertEqual(code, 0, out)
        self.assertIn("no manual edits: yes", out)

        fixed = state.model_copy(update={"fix_changes": [FileChange(path="src/main.ts", operation="update",
                                                                     content="v3\n", reason="fix")]})
        apply_fix_node(fixed, root=self.root)
        manifest = json.loads((self.root / "generated/block-dodger" / MANIFEST_FILE).read_text())
        self.assertEqual(manifest["written_by"], "apply_fix")
        self.assertEqual(self.audit()[0], 0)  # the fix came through the pipeline

        (self.root / "generated/block-dodger/src/main.ts").write_text("hand edit\n")
        (self.root / "generated/block-dodger/src/extra.ts").write_text("x\n")
        code, out = self.audit()
        self.assertEqual(code, 1, out)
        self.assertIn("CHANGED src/main.ts", out)
        self.assertIn("ADDED   src/extra.ts", out)
        self.assertIn("no manual edits: NO (2 file(s) differ)", out)

    def test_no_manifest_and_bad_dir(self):
        (self.root / "generated/old/src").mkdir(parents=True)
        self.assertEqual(self.audit("generated/old")[0], 1)
        self.assertEqual(self.audit("agents")[0], 2)


if __name__ == "__main__":
    unittest.main()
