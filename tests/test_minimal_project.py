import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.generators import minimal_project as mp  # noqa: E402
from agents.schemas import CommandResult  # noqa: E402
from agents.tools.safety import package_json_problems  # noqa: E402

TARGET = "generated/sample-game"


def cmd(command: str, exit_code: int = 0) -> CommandResult:
    return CommandResult(command=command, cwd=TARGET, exit_code=exit_code, duration_s=0.1)


class ChangesTest(unittest.TestCase):
    def setUp(self):
        self.changes = {c.path: c for c in mp.minimal_project_changes("sample-game", "Sample Game").changes}

    def test_three_files_created(self):
        self.assertEqual(list(self.changes), ["package.json", "index.html", "src/main.ts"])
        self.assertTrue(all(c.operation == "create" for c in self.changes.values()))

    def test_package_json(self):
        content = self.changes["package.json"].content
        self.assertEqual(package_json_problems(content, require_build=True), [])
        data = json.loads(content)
        self.assertEqual(data["scripts"]["build"], "vite build")
        self.assertEqual(data["devDependencies"], {"typescript": mp.TYPESCRIPT_VERSION, "vite": mp.VITE_VERSION})
        for version in data["devDependencies"].values():
            self.assertRegex(version, r"^\d+\.\d+\.\d+$", "versions must be exact pins")
        self.assertNotIn("dependencies", data)  # no phaser yet

    def test_index_and_main(self):
        self.assertIn('<script type="module" src="/src/main.ts"></script>', self.changes["index.html"].content)
        self.assertIn("<title>Sample Game</title>", self.changes["index.html"].content)
        main = self.changes["src/main.ts"].content
        self.assertIn("window.__GAME_STATE__ = { ready: true", main)
        self.assertNotIn("phaser", main.lower())

    def test_existing_files_become_updates(self):
        changes = mp.minimal_project_changes("x", "X", existing={"package.json"}).changes
        self.assertEqual([c.operation for c in changes], ["update", "create", "create"])

    def test_title_is_escaped_in_ts(self):
        main = mp.minimal_project_changes("x", 'Say "hi"').changes[2].content
        self.assertIn('"Say \\"hi\\""', main)


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "generated").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def generate(self, **kw):
        return mp.generate_minimal_project(TARGET, root=self.root, **kw)

    def make_dist(self, *_args, **_kw):
        (self.root / TARGET / "dist").mkdir(exist_ok=True)
        (self.root / TARGET / "dist/index.html").write_text("<html></html>")
        return cmd("npm run build")

    def test_dry_run_writes_nothing(self):
        with mock.patch.object(mp, "run_command") as run:
            report = self.generate(apply=False)
        self.assertTrue(report.ok)
        self.assertIsNone(report.applied)
        self.assertFalse((self.root / TARGET).exists())
        run.assert_not_called()

    def test_apply_without_commands(self):
        report = self.generate(install=False, build=False)
        self.assertTrue(report.ok, report.error)
        self.assertEqual(report.applied.changed_files,
                         [f"{TARGET}/package.json", f"{TARGET}/index.html", f"{TARGET}/src/main.ts"])
        self.assertIn("Sample Game", (self.root / TARGET / "index.html").read_text())

    def test_rerun_is_idempotent(self):
        self.generate(install=False, build=False)
        report = self.generate(install=False, build=False)
        self.assertTrue(report.ok, report.error)
        self.assertEqual({p.operation for p in report.preview.planned}, {"update"})

    def test_full_flow_with_mocked_commands(self):
        calls = []

        def fake_run(command, cwd, timeout, root):
            calls.append((command, cwd, timeout))
            return self.make_dist() if command == "npm run build" else cmd(command)

        with mock.patch.object(mp, "run_command", side_effect=fake_run):
            report = self.generate()
        self.assertTrue(report.ok, report.error)
        self.assertEqual([c[0] for c in calls], ["npm install", "npm run build"])
        self.assertEqual(calls[0][1], TARGET)
        self.assertEqual(report.dist_files, ["index.html"])

    def test_install_failure_stops_build(self):
        with mock.patch.object(mp, "run_command", return_value=cmd("npm install", 1)) as run:
            report = self.generate()
        self.assertFalse(report.ok)
        self.assertIn("'npm install' failed with exit code 1", report.error)
        self.assertEqual(run.call_count, 1)

    def test_build_failure(self):
        with mock.patch.object(mp, "run_command", side_effect=[cmd("npm install"), cmd("npm run build", 2)]):
            report = self.generate()
        self.assertIn("'npm run build' failed with exit code 2", report.error)

    def test_missing_dist(self):
        with mock.patch.object(mp, "run_command", side_effect=[cmd("npm install"), cmd("npm run build")]):
            report = self.generate()
        self.assertEqual(report.error, "build finished but dist/index.html is missing")

    def test_bad_target_rejected(self):
        from agents.tools.safety import SafetyError
        for target in ["agents/x", "/tmp/x", "generated"]:
            with self.subTest(target=target), self.assertRaises(SafetyError):
                mp.generate_minimal_project(target, root=self.root)


class ScriptTest(unittest.TestCase):
    def test_dry_run_script(self):
        target = "generated/test-dry-run-only"
        proc = subprocess.run([sys.executable, "scripts/generate_sample_game.py", "--target", target, "--dry-run"],
                              cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(f"DRY RUN · {target} · 3 change(s)", proc.stdout)
        self.assertFalse((ROOT / target).exists())

    def test_bad_target_script(self):
        proc = subprocess.run([sys.executable, "scripts/generate_sample_game.py", "--target", "agents/x", "--dry-run"],
                              cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 2)


@unittest.skipUnless(os.environ.get("RUN_NPM_TESTS") == "1", "set RUN_NPM_TESTS=1 (needs network for npm install)")
class RealNpmTest(unittest.TestCase):
    def test_install_and_build_in_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "generated").mkdir()
            report = mp.generate_minimal_project("generated/npm-check", title="Npm Check", root=root)
            self.assertTrue(report.ok, report.error and report.error + "\n" + report.commands[-1].stderr[-2000:])
            self.assertEqual([c.exit_code for c in report.commands], [0, 0])
            self.assertIn("index.html", report.dist_files)
            js = [p for p in (root / "generated/npm-check/dist").rglob("*.js")]
            self.assertTrue(any("Npm Check" in p.read_text() for p in js), "title must be in the built JS")


if __name__ == "__main__":
    unittest.main()
