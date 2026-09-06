from __future__ import annotations

import unittest

from scripts.validate_completion_evidence import validate


class CompletionEvidenceTests(unittest.TestCase):
    def base(self):
        return {
            "schema_version": 1,
            "task_id": "task-001",
            "conditions": [
                {"condition_id": "tests", "type": "tests_pass", "required": True},
                {"condition_id": "artifact", "type": "artifact_present", "required": True},
            ],
            "evidence": [
                {"condition_id": "tests", "status": "verified", "verifier": "deterministic", "pass_count": 3, "fail_count": 0},
                {"condition_id": "artifact", "status": "verified", "verifier": "deterministic", "artifact_ref": "artifact:sha256:" + "a" * 64},
            ],
        }

    def test_clean_evidence_passes(self):
        result = validate(self.base())
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["complete"])

    def test_missing_evidence_is_inconclusive(self):
        payload = self.base()
        payload["evidence"] = payload["evidence"][:1]
        result = validate(payload)
        self.assertEqual(result["status"], "inconclusive")
        self.assertFalse(result["complete"])

    def test_failed_condition_is_blocked(self):
        payload = self.base()
        payload["evidence"][0]["status"] = "failed"
        result = validate(payload)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["complete"])

    def test_nonzero_exit_is_blocked(self):
        payload = self.base()
        payload["conditions"][0] = {"condition_id": "command", "type": "command_exit_zero", "required": True}
        payload["evidence"][0] = {"condition_id": "command", "status": "verified", "verifier": "deterministic", "exit_code": 1}
        result = validate(payload)
        self.assertEqual(result["status"], "blocked")

    def test_malformed_evidence_is_inconclusive(self):
        payload = self.base()
        payload["evidence"][0]["verifier"] = "llm"
        result = validate(payload)
        self.assertEqual(result["status"], "inconclusive")
        self.assertFalse(result["complete"])

    def test_failed_judge_cannot_turn_into_pass(self):
        payload = self.base()
        payload["evidence"][0]["status"] = "failed"
        payload["evidence"][1]["status"] = "failed"
        result = validate(payload)
        self.assertNotEqual(result["status"], "passed")


if __name__ == "__main__":
    unittest.main()
