from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "live_shadow_policy.py"


def request(**overrides):
    value = {
        "schema_version": 1,
        "request_id": "turn-test-001",
        "final_text": "Answer includes evidence.",
        "metadata": {
            "agent_configuration_id": "agent-test-v1",
            "evaluator_configuration_id": "evaluator-test-v1",
        },
        "policy": {
            "required_patterns": ["evidence"],
            "forbidden_patterns": [],
        },
    }
    value.update(overrides)
    return value


class LiveShadowPolicyTests(unittest.TestCase):
    def run_cli(self, payload, *, evidence=False):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.jsonl"
            args = [sys.executable, str(SCRIPT)]
            if evidence:
                args += ["--evidence-output", str(output)]
            proc = subprocess.run(
                args,
                input=json.dumps(payload),
                text=True,
                capture_output=True,
            )
            decision = json.loads(proc.stdout)
            records = output.read_text().splitlines() if output.exists() else []
            return proc, decision, records

    def test_pass_returns_original_as_approved_transient_value(self):
        proc, decision, _ = self.run_cli(request())
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(decision["status"], "passed")
        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["final_text"], "Answer includes evidence.")

    def test_block_returns_no_replacement_text(self):
        payload = request(final_text="Answer without required marker.")
        proc, decision, _ = self.run_cli(payload)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(decision["status"], "blocked")
        self.assertFalse(decision["allowed"])
        self.assertIsNone(decision["final_text"])

    def test_invalid_policy_returns_inconclusive(self):
        payload = request(policy={"required_patterns": ["["]})
        proc, decision, _ = self.run_cli(payload)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(decision["status"], "inconclusive")
        self.assertIsNone(decision["final_text"])

    def test_invalid_request_fails_closed(self):
        proc, decision, _ = self.run_cli({"schema_version": 2})
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(decision["status"], "inconclusive")
        self.assertFalse(decision["allowed"])
        self.assertIsNone(decision["final_text"])

    def test_evidence_is_metadata_first_and_excludes_raw_text(self):
        raw = "Answer includes evidence."
        proc, decision, records = self.run_cli(request(), evidence=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(decision["status"], "passed")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertNotIn(raw, record)
        self.assertIn("input_ref", record)
        self.assertEqual(json.loads(record)["evidence_class"], "O")


if __name__ == "__main__":
    unittest.main()
