#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "validated_command_runner.py"
PRODUCER_BAD = ROOT / "tests" / "fixtures" / "producer_bad.py"
PRODUCER_GOOD = ROOT / "tests" / "fixtures" / "producer_good.py"
CORRECTOR = ROOT / "tests" / "fixtures" / "correction_agent.py"
RULES = {"required_patterns": ["根拠"], "forbidden_patterns": ["未確認の断定"]}


def execute(producer: Path, correction: Path | None = None) -> tuple[int, dict]:
    command = [sys.executable, str(RUNNER), "--producer", f"{sys.executable} {producer}"]
    if correction:
        command += ["--correction", f"{sys.executable} {correction}"]
    request = {"input": "検証して", "rules": RULES}
    proc = subprocess.run(command, input=json.dumps(request), text=True, capture_output=True)
    return proc.returncode, json.loads(proc.stdout)


class ValidatedCommandRunnerTests(unittest.TestCase):
    def test_producer_and_correction_agent_complete_two_pass_flow(self):
        code, result = execute(PRODUCER_BAD, CORRECTOR)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["delivery_allowed"])
        self.assertEqual(result["final_response"], "根拠を確認しました。")
        self.assertEqual(len(result["attempts"]), 2)

    def test_bad_producer_without_correction_is_blocked(self):
        code, result = execute(PRODUCER_BAD)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["delivery_allowed"])
        self.assertIsNone(result["final_response"])

    def test_good_producer_does_not_need_correction(self):
        code, result = execute(PRODUCER_GOOD, CORRECTOR)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["attempts"]), 1)

    def test_missing_correction_command_is_not_silent_success(self):
        missing = ROOT / "tests" / "fixtures" / "does-not-exist.py"
        code, result = execute(PRODUCER_BAD, missing)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "inconclusive")
        self.assertFalse(result["delivery_allowed"])
        self.assertIsNone(result["final_response"])


if __name__ == "__main__":
    unittest.main()
