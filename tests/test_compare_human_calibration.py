from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compare_human_calibration.py"
CASE = ROOT / "tests" / "fixtures" / "real-conversation-vc-pitch-boundary.json"


class HumanCalibrationComparisonTests(unittest.TestCase):
    def test_identical_raters_are_full_agreement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--rater-a", str(CASE), "--rater-b", str(CASE), "--output", str(output)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["agreement_count"], 5)
            self.assertEqual(result["agreement_rate"], 1.0)

    def test_disagreement_categories_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / "rater-b.json"
            output = Path(directory) / "result.json"
            value = json.loads(CASE.read_text(encoding="utf-8"))
            for item in value["human_calibration"]:
                if item["axis"] == "initial_question_capture":
                    item["status"] = "pass"
                if item["axis"] == "feedback_interpretation":
                    item["status"] = "not_observable"
            altered.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--rater-a", str(CASE), "--rater-b", str(altered), "--output", str(output)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["comparison_counts"]["undercall"], 1)
            self.assertEqual(result["comparison_counts"]["unobservable_mismatch"], 1)
            self.assertEqual(result["agreement_count"], 3)


if __name__ == "__main__":
    unittest.main()
