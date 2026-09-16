from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compare_real_conversation_cases.py"
CASES = [
    ROOT / "tests" / "fixtures" / "real-conversation-embedded-connectivity.json",
    ROOT / "tests" / "fixtures" / "real-conversation-correction-rollback.json",
    ROOT / "tests" / "fixtures" / "real-conversation-no-go.json",
    ROOT / "tests" / "fixtures" / "real-conversation-insufficient-evidence.json",
]


class RealConversationComparisonTests(unittest.TestCase):
    def test_comparison_preserves_distinct_statuses_and_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "comparison.json"
            command = [sys.executable, str(SCRIPT)]
            for case in CASES:
                command.extend(["--case", str(case)])
            command.extend(["--output", str(output)])
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["case_count"], 4)
            self.assertEqual(report["decision_statuses"], ["no_go", "on_hold", "provisionally_locked"])
            rows = {row["scenario_id"]: row for row in report["rows"]}
            self.assertEqual(rows["energy-management-saas-no-go"]["decision_status"], "no_go")
            self.assertEqual(rows["customer-provider-classification-rollback"]["decision_status"], "on_hold")
            self.assertTrue(rows["insufficient-evidence-safe-stop"]["requires_semantic_review"])
            self.assertTrue(rows["insufficient-evidence-safe-stop"]["negative_feedback_observed"])
            self.assertIn("evidence_driven_update", rows["insufficient-evidence-safe-stop"]["human_non_pass_axes"])
            self.assertFalse(report["rows"][0]["semantic_outcome_proven"])
            self.assertFalse(report["rows"][0]["raw_text_persisted"])
            self.assertFalse(report["rows"][0]["session_id_persisted"])


if __name__ == "__main__":
    unittest.main()
