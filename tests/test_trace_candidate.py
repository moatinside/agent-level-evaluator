from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.trace_candidate import build_candidate


class TraceCandidateTests(unittest.TestCase):
    def test_builds_sanitized_approval_gated_candidate(self):
        trace = {
            "prompt": "Review /Users/yokapro/private.txt token=secret-value",
            "tool_calls": ["read_file", "terminal"],
            "outcome": "https://alice:pw@example.com completed",
            "criteria": ["tests pass"],
        }
        candidate = build_candidate(trace)
        rendered = json.dumps(candidate, ensure_ascii=False)
        self.assertEqual(candidate["status"], "candidate")
        self.assertTrue(candidate["sanitized"])
        self.assertTrue(candidate["requires_human_approval"])
        self.assertNotIn("secret-value", rendered)
        self.assertNotIn("alice:pw", rendered)
        self.assertNotIn("/Users/yokapro", rendered)
        self.assertNotIn("outcome", candidate)
        self.assertEqual(candidate["allowed_tools"], ["read_file", "terminal"])

    def test_rejects_missing_outcome(self):
        with self.assertRaises(ValueError):
            build_candidate({"prompt": "task", "criteria": ["done"]})

    def test_cli_writes_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "trace.json"
            output = root / "candidate.json"
            source.write_text(json.dumps({
                "prompt": "task",
                "tool_calls": ["read_file"],
                "outcome": "done",
                "criteria": ["result exists"],
            }))
            proc = subprocess.run(
                [sys.executable, "scripts/trace_candidate.py", "--input", str(source), "--output", str(output)],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(json.loads(output.read_text())["status"], "candidate")


if __name__ == "__main__":
    unittest.main()
