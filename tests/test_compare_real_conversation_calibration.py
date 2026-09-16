from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compare_real_conversation_calibration.py"
CASES = [
    ROOT / "tests" / "fixtures" / "real-conversation-embedded-connectivity.json",
    ROOT / "tests" / "fixtures" / "real-conversation-correction-rollback.json",
    ROOT / "tests" / "fixtures" / "real-conversation-no-go.json",
    ROOT / "tests" / "fixtures" / "real-conversation-vc-pitch-boundary.json",
]


class RealConversationCalibrationComparisonTests(unittest.TestCase):
    def test_compares_only_real_cases_and_keeps_axis_distribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calibration.json"
            command = [sys.executable, str(SCRIPT)]
            for case in CASES:
                command.extend(["--case", str(case)])
            command.extend(["--output", str(output)])
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["case_count"], 4)
            self.assertFalse(report["interpretation_boundary"]["synthetic_cases_included"])
            self.assertEqual(report["status_distribution_by_axis"]["initial_question_capture"], {"pass": 2, "partial": 2})
            self.assertEqual(report["status_distribution_by_axis"]["evidence_driven_update"], {"pass": 2, "partial": 2})
            self.assertEqual(report["status_distribution_by_axis"]["decision_proximity"], {"partial": 4})
            ids = {row["scenario_id"] for row in report["rows"]}
            self.assertNotIn("insufficient-evidence-safe-stop", ids)

    def test_rejects_controlled_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calibration.json"
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--case", str(ROOT / "tests" / "fixtures" / "real-conversation-insufficient-evidence.json"), "--output", str(output)],
                capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
