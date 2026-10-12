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
SMOKE_GRAPH_SHA256 = "e0ff1d10a2ea82d99209d8b77d7b172e469482b2b4545b497ea8ec154b306b76"


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
