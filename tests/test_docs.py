import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

README_SECTIONS = [
    "## What this project is",
    "We are not manually building a game yet",
    "## Project goal",
    "## Tech stack",
    "## Current status",
    "## Setup",
    "## Activate the venv",
    "## Run agents/smoke_graph.py",
    "## Roadmap summary",
    "## Safety rules",
]

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def relative_links(md_path: Path) -> list[str]:
    links = MD_LINK.findall(md_path.read_text())
    return [l.split("#")[0] for l in links if not re.match(r"^[a-z]+:", l) and not l.startswith("#")]


class DocsTest(unittest.TestCase):
    def test_readme_has_required_sections(self):
        text = (ROOT / "README.md").read_text()
        for section in README_SECTIONS:
            with self.subTest(section=section):
                self.assertIn(section, text)

    def test_roadmap_lists_all_milestones(self):
        text = (ROOT / "docs/ROADMAP.md").read_text()
        for n in range(1, 21):
            with self.subTest(milestone=n):
                self.assertRegex(text, rf"## Milestone {n} — ")

    def test_claude_md_links_resolve(self):
        links = relative_links(ROOT / "CLAUDE.md")
        self.assertTrue(links, "CLAUDE.md has no links — it must be the docs index")
        for link in links:
            with self.subTest(link=link):
                self.assertTrue((ROOT / link).is_file(), f"broken link in CLAUDE.md: {link}")

    def test_every_doc_is_indexed_in_claude_md(self):
        indexed = set(relative_links(ROOT / "CLAUDE.md"))
        for doc in sorted((ROOT / "docs").rglob("*.md")):
            rel = doc.relative_to(ROOT).as_posix()
            with self.subTest(doc=rel):
                self.assertIn(rel, indexed, f"{rel} is not listed in CLAUDE.md")

    def test_docs_links_resolve(self):
        for doc in sorted([ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]):
            for link in relative_links(doc):
                with self.subTest(doc=doc.name, link=link):
                    self.assertTrue((doc.parent / link).exists(), f"broken link in {doc.name}: {link}")


if __name__ == "__main__":
    unittest.main()
