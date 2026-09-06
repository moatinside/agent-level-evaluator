from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.experience_ledger import approve_record, append_record, build_record, retrieve, validate_record


class ExperienceLedgerTests(unittest.TestCase):
    def payload(self, **overrides):
        value = {
            "experience_id": "experience:run-001",
            "task_ref": "task:response-validation",
            "configuration_id": "config:hermes-v1",
            "outcome": "blocked",
            "failure_class": "validation",
            "evidence_refs": ["run:shadow-001"],
            "lesson": "A required pattern was absent; stop delivery and request correction.",
            "source": "deterministic",
            "created_at": "2026-09-06T00:00:00Z",
        }
        value.update(overrides)
        return value

    def test_build_is_metadata_first(self):
        record = build_record(self.payload())
        self.assertNotIn("lesson", record)
        self.assertTrue(record["lesson_ref"].startswith("lesson:sha256:"))
        self.assertEqual(record["approval"], "pending")
        self.assertEqual(validate_record(record)["status"], "valid")
        self.assertNotIn("secret-value", record["lesson_summary"])

    def test_approved_record_requires_auditable_approval_fields(self):
        record = build_record(self.payload())
        record["approval"] = "approved"
        self.assertEqual(validate_record(record)["status"], "inconclusive")

    def test_invalid_outcome_cannot_be_recorded(self):
        with self.assertRaises(ValueError):
            build_record(self.payload(outcome="passed", failure_class="validation"))

    def test_non_passed_requires_failure_class(self):
        with self.assertRaises(ValueError):
            build_record(self.payload(outcome="blocked", failure_class="none"))

    def test_retrieval_requires_approval_and_same_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "experience.jsonl"
            pending = build_record(self.payload())
            append_record(ledger, pending)
            self.assertEqual(retrieve(ledger, "task:response-validation", "config:hermes-v1"), [])
            approved = approve_record(ledger, pending["experience_id"], "person:reviewer-1", "reason:accepted-1", "2026-09-06T01:00:00Z")
            self.assertEqual(approved["approval"], "approved")
            with self.assertRaises(ValueError):
                approve_record(ledger, pending["experience_id"], "person:reviewer-1", "reason:accepted-1", "2026-09-06T01:00:00Z")
            other = build_record(self.payload(experience_id="experience:run-002", configuration_id="config:other"))
            append_record(ledger, other)
            found = retrieve(ledger, "task:response-validation", "config:hermes-v1")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["experience_id"], "experience:run-001")

    def test_malformed_ledger_line_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "experience.jsonl"
            ledger.write_text("not-json\n", encoding="utf-8")
            self.assertEqual(retrieve(ledger, "task:x", "config:x"), [])

    def test_invalid_record_is_not_valid(self):
        record = build_record(self.payload())
        record["lesson_ref"] = "lesson:raw-text"
        self.assertEqual(validate_record(record)["status"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
