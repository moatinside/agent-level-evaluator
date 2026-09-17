from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "scripts" / "hermes_shadow_adapter.py"


def event(**overrides):
    value = {
        "schema_version": 1,
        "event_type": "completed_response",
        "request_id": "hermes-turn-001",
        "final_text": "Answer includes evidence.",
        "metadata": {
            "agent_configuration_id": "sha256:" + "a" * 64,
            "evaluator_configuration_id": "sha256:" + "b" * 64,
            "trigger_origin": "hermes",
        },
        "policy": {"required_patterns": ["evidence"], "forbidden_patterns": []},
        "trace": {"tool_count": 2, "step_count": 3},
    }
    value.update(overrides)
    return value


class HermesShadowAdapterTests(unittest.TestCase):
    def run_adapter(self, payload, *, blocker=False):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.jsonl"
            if blocker:
                output = Path(directory) / "blocker" / "evidence.jsonl"
                output.parent.write_text("not a directory", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ADAPTER), "--evidence-output", str(output)],
                input=json.dumps(payload), text=True, capture_output=True,
            )
            records = output.read_text(encoding="utf-8").splitlines() if output.exists() else []
            return proc, json.loads(proc.stdout), records

    def test_hermes_event_is_validated_and_persisted_without_delivery(self):
        proc, decision, records = self.run_adapter(event())
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(decision["adapter"], "hermes_shadow")
        self.assertTrue(decision["evidence_persisted"])
        self.assertFalse(decision["delivery_attempted"])
        self.assertEqual(decision["side_effect_status"], "not_attempted")
        self.assertEqual(decision["trace_metadata"], {"tool_count": 2, "step_count": 3})
        self.assertEqual(len(records), 1)
        record = json.loads(records[0])
        self.assertEqual(record["trigger_origin"], "hermes")
        self.assertEqual(record["execution_mode"], "shadow")
        self.assertNotIn(event()["final_text"], records[0])
        self.assertNotIn("transcript", record)

    def test_non_hermes_origin_is_rejected_without_evidence(self):
        payload = event(metadata={
            "agent_configuration_id": "sha256:" + "a" * 64,
            "evaluator_configuration_id": "sha256:" + "b" * 64,
            "trigger_origin": "harness",
        })
        proc, decision, records = self.run_adapter(payload)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(decision["status"], "inconclusive")
        self.assertEqual(decision["evidence_error_code"], "invalid_runtime_event")
        self.assertEqual(records, [])

    def test_shadow_validation_failure_never_delivers_text(self):
        proc, decision, records = self.run_adapter(event(final_text="Answer without marker."))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(decision["status"], "blocked")
        self.assertFalse(decision["allowed"])
        self.assertIsNone(decision["final_text"])
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0])["side_effect_status"], "not_attempted")

    def test_evidence_failure_preserves_validator_decision(self):
        proc, decision, records = self.run_adapter(event(), blocker=True)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(decision["status"], "passed")
        self.assertTrue(decision["allowed"])
        self.assertFalse(decision["evidence_persisted"])
        self.assertEqual(decision["evidence_error_code"], "evidence_write_failed")
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
