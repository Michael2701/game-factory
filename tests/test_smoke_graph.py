import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(os.environ.get("RUN_OLLAMA_TESTS") == "1", "set RUN_OLLAMA_TESTS=1 (needs `ollama serve`)")
class SmokeGraphTest(unittest.TestCase):
    def test_smoke_graph_runs(self):
        # smoke_graph.py invokes the graph at import time, so run it as a subprocess.
        proc = subprocess.run(
            [sys.executable, "agents/smoke_graph.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("=== SPEC ===", proc.stdout)
        self.assertIn("=== REVIEW ===", proc.stdout)


if __name__ == "__main__":
    unittest.main()
