import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.nodes.applier import TARGET_REFUSED, apply_node, check_target, final_changes  # noqa: E402
from agents.schemas import FactoryStatus, FileChange, GameFactoryState  # noqa: E402
from agents.schemas.examples import BLOCK_DODGER_IDEA, sample_game_spec  # noqa: E402
from agents.tools.safety import SafetyError  # noqa: E402

PACKAGE = json.dumps({"name": "block-dodger", "private": True, "scripts": {"build": "vite build"}})


def fc(path, op, content=None):
    return FileChange(path=path, operation=op, content=content, reason="r")


def make_state(code=None, tests=None, target_dir=None) -> GameFactoryState:
    code = code if code is not None else [
        fc("package.json", "create", PACKAGE),
        fc("src/main.ts", "create", "v1\n"),
        fc("src/scenes/GameScene.ts", "create", "scene\n"),
        fc("src/main.ts", "update", "v2\n"),
    ]
    tests = tests if tests is not None else [fc("tests/game.spec.ts", "create", "spec\n"),
                                             fc("playwright.config.ts", "create", "config\n")]
    return GameFactoryState(user_idea=BLOCK_DODGER_IDEA, game_spec=sample_game_spec(), proposed_changes=code,
                            proposed_test_changes=tests, target_dir=target_dir,
                            status=FactoryStatus.CHANGES_PROPOSED)


def tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


class TempRootTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        for d in ("generated", "games", "templates", "agents"):
            (self.root / d).mkdir()

    def tearDown(self):
        self._tmp.cleanup()


class FinalChangesTest(unittest.TestCase):
    def test_merges_chain_into_one_create_per_file(self):
        changes = final_changes(make_state())
        self.assertEqual([c.path for c in changes], ["package.json", "src/main.ts", "src/scenes/GameScene.ts",
                                                     "tests/game.spec.ts", "playwright.config.ts"])
        self.assertTrue(all(c.operation == "create" for c in changes))
        self.assertEqual(changes[1].content, "v2\n")  # latest version of main.ts

    def test_delete_drops_file(self):
        state = make_state(code=[fc("a.ts", "create", "a"), fc("b.ts", "create", "b"), fc("a.ts", "delete")])
        self.assertNotIn("a.ts", [c.path for c in final_changes(state)])


class CheckTargetTest(TempRootTest):
    def test_accepts_new_or_empty_folder(self):
        self.assertEqual(check_target("generated/new-game", self.root), "generated/new-game")
        (self.root / "games/empty").mkdir()
        self.assertEqual(check_target("games/empty", self.root), "games/empty")
        self.assertEqual(check_target(self.root / "generated/abs", self.root), "generated/abs")

    def test_rejects(self):
        (self.root / "generated/full").mkdir()
        (self.root / "generated/full/x.txt").write_text("x")
        (self.root / "generated/file").write_text("x")
        for bad in ["generated/full", "generated/file", "templates/x", "generated", "games", "agents/x", "x",
                    "../x", "/etc/x", "~/x", "generated/.env", "generated/x/../../agents"]:
            with self.subTest(target=bad), self.assertRaises(SafetyError):
                check_target(bad, self.root)


class ApplyNodeTest(TempRootTest):
    def test_writes_final_project_to_default_target(self):
        out = apply_node(make_state(), root=self.root)
        self.assertEqual(out["status"], FactoryStatus.CHANGES_APPLIED, out.get("error"))
        target = self.root / "generated/block-dodger"
        self.assertEqual(out["target_dir"], "generated/block-dodger")
        self.assertEqual(tree(target), ["package.json", "playwright.config.ts", "src/main.ts",
                                        "src/scenes/GameScene.ts", "tests/game.spec.ts"])
        self.assertEqual((target / "src/main.ts").read_text(), "v2\n")
        self.assertEqual(sorted(out["changed_files"]), sorted(f"generated/block-dodger/{p}" for p in tree(target)))
        self.assertEqual(tree(self.root), sorted(out["changed_files"]))  # nothing else written

    def test_explicit_target(self):
        out = apply_node(make_state(target_dir="games/dodger-v1"), root=self.root)
        self.assertEqual(out["status"], FactoryStatus.CHANGES_APPLIED, out.get("error"))
        self.assertTrue((self.root / "games/dodger-v1/src/main.ts").is_file())

    def test_refuses_non_empty_target_and_writes_nothing(self):
        existing = self.root / "generated/block-dodger"
        existing.mkdir()
        (existing / "keep.txt").write_text("mine")
        out = apply_node(make_state(), root=self.root)
        self.assertEqual(out["status"], FactoryStatus.ERROR)
        self.assertTrue(out["error"].startswith(f"applier: {TARGET_REFUSED}: "), out["error"])
        self.assertEqual(tree(self.root), ["generated/block-dodger/keep.txt"])

    def test_refuses_target_outside_apply_roots(self):
        for bad in ["templates/x", "agents/x", "generated"]:
            with self.subTest(target=bad):
                out = apply_node(make_state(target_dir=bad), root=self.root)
                self.assertTrue(out["error"].startswith(f"applier: {TARGET_REFUSED}: "), out["error"])
        self.assertEqual(tree(self.root), [])

    def test_unsafe_proposal_rejects_everything(self):
        evil = FileChange.model_construct(path="../../agents/evil.py", operation="create", content="x",
                                          patch=None, reason="r")  # bypasses the schema's '..' check
        cases = {
            "parent path": [fc("src/main.ts", "create", "ok\n"), evil],
            "protected": [fc("src/main.ts", "create", "ok\n"), fc(".env", "create", "SECRET=1")],
            "bad package.json": [fc("package.json", "create", json.dumps({"scripts": {"build": "rm -rf /"}}))],
            "too large": [fc("big.ts", "create", "x" * 2_000_000)],
        }
        for name, code in cases.items():
            with self.subTest(case=name):
                out = apply_node(make_state(code=code), root=self.root)
                self.assertEqual(out["status"], FactoryStatus.ERROR)
                self.assertIn("REJECTED", out["error"])
                self.assertEqual(tree(self.root), [])

    def test_nothing_to_apply(self):
        state = GameFactoryState(user_idea=BLOCK_DODGER_IDEA, game_spec=sample_game_spec())
        out = apply_node(state, root=self.root)
        self.assertEqual(out["status"], FactoryStatus.ERROR)
        self.assertIn("nothing to apply", out["error"])


if __name__ == "__main__":
    unittest.main()
