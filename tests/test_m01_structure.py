import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_DIRS = [
    "agents",
    "agents/nodes",
    "agents/schemas",
    "agents/tools",
    "agents/prompts",
    "games",
    "templates",
    "scripts",
    "docs",
    "docs/milestones",
    "tests",
]

PACKAGES = ["agents", "agents/nodes", "agents/schemas", "agents/tools"]

# sha256 of agents/smoke_graph.py before Milestone 1; the file must stay untouched.
# M21b: the only change since M1 is the model line (now $GAME_FACTORY_MODEL, the 14b was removed), approved by the user
SMOKE_GRAPH_SHA256 = "2434b384453e3a72d507a25bab590d90c79ae641c478085f34f32d2e521acaeb"


class ProjectStructureTest(unittest.TestCase):
    def test_required_dirs_exist(self):
        for rel in REQUIRED_DIRS:
            with self.subTest(dir=rel):
                self.assertTrue((ROOT / rel).is_dir(), f"missing directory: {rel}")

    def test_packages_have_init(self):
        for rel in PACKAGES:
            with self.subTest(package=rel):
                self.assertTrue((ROOT / rel / "__init__.py").is_file(), f"missing {rel}/__init__.py")

    def test_smoke_graph_unchanged(self):
        digest = hashlib.sha256((ROOT / "agents/smoke_graph.py").read_bytes()).hexdigest()
        self.assertEqual(digest, SMOKE_GRAPH_SHA256, "agents/smoke_graph.py was modified")

    def test_gitignore_excludes_venv(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertIn(".venv/", lines)


if __name__ == "__main__":
    unittest.main()
