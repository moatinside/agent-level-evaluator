#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_51_point_shadow.py"
CASES = ROOT / "tests" / "fixtures" / "51-point-cases.json"


class FiftyOnePointShadowTests(unittest.TestCase):
    def test_gate_separates_pass_safe_stop_and_unobserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "operational-evidence" / "51-point.jsonl"
            command = [
                sys.executable, str(RUNNER), "--cases", str(CASES),
                "--output", str(output),
                "--agent-configuration-id", "sha256:" + "a" * 64,
                "--evaluator-configuration-id", "sha256:" + "b" * 64,
            ]
            process = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            summary = json.loads(process.stdout)
            self.assertEqual(summary["counts"], {"total": 3, "passed": 1, "failed": 0, "blocked": 1, "inconclusive": 1})
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["result"] for r in records], ["passed", "blocked", "inconclusive"])
            self.assertTrue(all(r["environment_class"] == "shadow" for r in records))
            self.assertTrue(all(r["side_effect_status"] == "not_attempted" for r in records))
            self.assertTrue(all(r["acceptance_results"]["51_point_gate"]["human_review_is_not_auto_promotion"] for r in records))


if __name__ == "__main__":
    unittest.main()
