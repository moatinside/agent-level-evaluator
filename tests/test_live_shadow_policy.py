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
            "agent_configuration_id": "sha256:" + "a" * 64,
            "evaluator_configuration_id": "sha256:" + "b" * 64,
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
        persisted = json.loads(record)
        self.assertEqual(persisted["trigger_origin"], "harness")
        self.assertEqual(persisted["execution_mode"], "shadow")
        self.assertEqual(persisted["decision"], "passed")
        self.assertEqual(persisted["side_effect_status"], "not_attempted")

    def test_shadow_blocked_is_policy_decision_without_delivery(self):
        payload = request(final_text="Answer without required marker.")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.jsonl"
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--evidence-output", str(output)],
                input=json.dumps(payload), text=True, capture_output=True,
            )
            self.assertEqual(proc.returncode, 1)
            decision = json.loads(proc.stdout)
            record = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
            validation = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "validate_stage1.py"), "--evidence", str(output)],
                text=True, capture_output=True,
            )
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(record["decision"], "blocked")
        self.assertEqual(record["side_effect_status"], "not_attempted")
        self.assertEqual(record["execution_mode"], "shadow")
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

    def test_invalid_configuration_ids_fail_closed_without_evidence_output(self):
        payload = request()
        payload["metadata"]["agent_configuration_id"] = "runtime-default"
        proc, decision, records = self.run_cli(payload)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(decision["status"], "inconclusive")
        self.assertFalse(decision["allowed"])
        self.assertIsNone(decision["final_text"])
        self.assertEqual(records, [])

    def test_evidence_write_failure_does_not_change_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "blocker"
            blocker.write_text("not a directory")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--evidence-output", str(blocker / "evidence.jsonl")],
                input=json.dumps(request()), text=True, capture_output=True,
            )
        decision = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(decision["status"], "passed")
        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["evidence_error_code"], "evidence_write_failed")


if __name__ == "__main__":
    unittest.main()
