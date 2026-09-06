from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.shadow_to_experience import convert, to_record


class ShadowToExperienceTests(unittest.TestCase):
    def evidence(self, result="blocked", suffix="1"):
        return {
            "assessment_id": f"assessment:shadow-{suffix}",
            "scenario_id": "case-1",
            "agent_configuration_id": "fixture-agent-v1",
            "result": result,
            "input_ref": "sha256:input-1",
            "validator_report_ref": "sha256:report-1",
            "ended_at": "2026-09-06T16:34:47Z",
        }

    def test_converts_without_raw_evidence(self):
        record = to_record(self.evidence())
        self.assertEqual(record["approval"], "pending")
        self.assertEqual(record["outcome"], "blocked")
        self.assertNotIn("scenario text", json.dumps(record))

    def test_batch_creates_pending_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "evidence.jsonl", root / "experience.jsonl"
            source.write_text("\n".join(json.dumps(self.evidence(result=x, suffix=str(i))) for i, x in enumerate(["passed", "blocked", "inconclusive"], 1)) + "\n", encoding="utf-8")
            counts = convert(source, output)
            self.assertEqual(counts, {"read": 3, "written": 3, "rejected": 0})
            records = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual({r["approval"] for r in records}, {"pending"})
            self.assertNotIn("prompt", output.read_text())

    def test_unknown_result_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "evidence.jsonl", root / "experience.jsonl"
            source.write_text(json.dumps(self.evidence(result="unknown-result")) + "\n", encoding="utf-8")
            counts = convert(source, output)
            self.assertEqual(counts["rejected"], 1)
            self.assertEqual(counts["written"], 0)


if __name__ == "__main__":
    unittest.main()
