from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_real_conversation_shadow.py"
CASE = ROOT / "tests" / "fixtures" / "real-conversation-embedded-connectivity.json"


class RealConversationShadowTests(unittest.TestCase):
    def test_trace_evidence_question_and_feedback_are_connected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "operational-evidence" / "real-conversation.jsonl"
            command = [
                sys.executable,
                str(RUNNER),
                "--case", str(CASE),
                "--output", str(output),
                "--agent-configuration-id", "sha256:" + "a" * 64,
                "--evaluator-configuration-id", "sha256:" + "b" * 64,
            ]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            record = json.loads(output.read_text(encoding="utf-8"))
            acceptance = record["acceptance_results"]
            self.assertEqual(record["result"], "passed")
            self.assertEqual(record["environment_class"], "shadow")
            self.assertEqual(record["evidence_class"], "O")
            self.assertTrue(acceptance["trace_present"])
            self.assertTrue(acceptance["question_changed"])
            self.assertEqual(acceptance["question_change_count"], 2)
            self.assertTrue(acceptance["evidence_linked_to_change"])
            self.assertTrue(acceptance["user_feedback_connected"])
            self.assertFalse(acceptance["raw_text_persisted"])
            self.assertFalse(acceptance["external_delivery"])
            self.assertFalse(acceptance["automatic_promotion"])
            self.assertIn("correction", acceptance["user_feedback_types"])
            self.assertIn("positive_signal", acceptance["user_feedback_types"])
            self.assertNotIn("session_id", record)
            self.assertNotIn("transcript", record)


if __name__ == "__main__":
    unittest.main()
