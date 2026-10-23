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


def _response(path: Path, rater_ref: str) -> Path:
    value = json.loads(CASE.read_text(encoding="utf-8"))
    value["rater_ref"] = rater_ref
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


class HumanCalibrationComparisonTests(unittest.TestCase):
    def test_same_file_is_rejected_as_inter_rater_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--rater-a", str(CASE), "--rater-b", str(CASE), "--output", str(output)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(
                json.loads(completed.stdout),
                {"status": "FAIL", "error": "rater_inputs_not_independent"},
            )
            self.assertFalse(output.exists())

    def test_same_rater_ref_is_rejected_even_when_labels_differ(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            rater_a = _response(directory_path / "rater-a.json", "rater:opaque-a")
            rater_b = _response(directory_path / "rater-b.json", "rater:opaque-a")
            output = directory_path / "result.json"
            value = json.loads(rater_b.read_text(encoding="utf-8"))
            value["human_calibration"][0]["status"] = "pass"
            rater_b.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--rater-a", str(rater_a), "--rater-b", str(rater_b), "--output", str(output)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(
                json.loads(completed.stdout),
                {"status": "FAIL", "error": "rater_inputs_not_independent"},
            )
            self.assertFalse(output.exists())

    def test_identical_labels_from_distinct_rater_refs_are_valid_agreement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            rater_a = _response(directory_path / "rater-a.json", "rater:opaque-a")
            rater_b = _response(directory_path / "rater-b.json", "rater:opaque-b")
            output = directory_path / "result.json"
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--rater-a", str(rater_a), "--rater-b", str(rater_b), "--output", str(output)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["agreement_count"], 5)
            self.assertEqual(result["agreement_rate"], 1.0)
            self.assertNotIn("rater_ref", json.dumps(result))

    def test_missing_or_invalid_rater_ref_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            rater_b = _response(directory_path / "rater-b.json", "rater:opaque-b")
            for case_number, invalid_ref in enumerate((None, "Reviewer A", 7)):
                with self.subTest(invalid_ref=invalid_ref):
                    rater_a = directory_path / f"rater-a-{case_number}.json"
                    value = json.loads(CASE.read_text(encoding="utf-8"))
                    if invalid_ref is not None:
                        value["rater_ref"] = invalid_ref
                    rater_a.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                    output = directory_path / f"result-{case_number}.json"
                    completed = subprocess.run(
                        [sys.executable, str(SCRIPT), "--rater-a", str(rater_a), "--rater-b", str(rater_b), "--output", str(output)],
                        capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(completed.returncode, 1)
                    self.assertEqual(json.loads(completed.stdout), {"status": "FAIL", "error": "invalid_rater_ref"})
                    self.assertFalse(output.exists())

    def test_same_input_smoke_is_explicitly_labeled_smoke_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            same_input = _response(directory_path / "rater-a.json", "rater:smoke")
            output = directory_path / "result.json"
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--rater-a", str(same_input), "--rater-b", str(same_input),
                 "--output", str(output), "--smoke-only"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "smoke_only")
            self.assertEqual(result["comparison_type"], "smoke_only")
            self.assertEqual(json.loads(completed.stdout)["status"], "smoke_only")

    def test_duplicate_calibration_axis_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            altered = _response(directory_path / "rater-b.json", "rater:opaque-b")
            rater_a = _response(directory_path / "rater-a.json", "rater:opaque-a")
            output = directory_path / "result.json"
            value = json.loads(altered.read_text(encoding="utf-8"))
            duplicate = dict(value["human_calibration"][0])
            duplicate["status"] = next(
                status for status in ("pass", "partial", "fail", "not_observable")
                if status != duplicate["status"]
            )
            value["human_calibration"].append(duplicate)
            altered.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--rater-a", str(rater_a), "--rater-b", str(altered), "--output", str(output)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(
                json.loads(completed.stdout),
                {"status": "FAIL", "error": "duplicate_calibration_axis"},
            )
            self.assertFalse(output.exists())

    def test_disagreement_categories_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            altered = _response(directory_path / "rater-b.json", "rater:opaque-b")
            rater_a = _response(directory_path / "rater-a.json", "rater:opaque-a")
            output = directory_path / "result.json"
            value = json.loads(altered.read_text(encoding="utf-8"))
            for item in value["human_calibration"]:
                if item["axis"] == "initial_question_capture":
                    item["status"] = "pass"
                if item["axis"] == "feedback_interpretation":
                    item["status"] = "not_observable"
            altered.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--rater-a", str(rater_a), "--rater-b", str(altered), "--output", str(output)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["comparison_counts"]["undercall"], 1)
            self.assertEqual(result["comparison_counts"]["unobservable_mismatch"], 1)
            self.assertEqual(result["agreement_count"], 3)


if __name__ == "__main__":
    unittest.main()
