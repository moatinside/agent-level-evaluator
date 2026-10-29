from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

fake_cycle: Any = types.ModuleType("run_conversation_review_cycle")
fake_cycle.evaluator = types.SimpleNamespace(
    make_review_report=lambda record: f"canonical:{record['evaluation_ref']}:{record['marker']}\n"
)
fake_cycle.format_failure_notice = lambda result: "failure"
fake_cycle.delivery_failure_notice = lambda: "delivery failure"
WRAPPER_PATH = Path.home() / ".hermes" / "scripts" / "agent-level-auto-evaluation.py"
EXPECTED_WRAPPER_SHA256 = "90a27f8a32f9ec567c1b3aae89532e791630eabbc20c31c5b91f2c0fa5bf2b4a"


def assert_reviewed_wrapper_bytes(path: Path) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != EXPECTED_WRAPPER_SHA256:
        raise AssertionError("installed Cron wrapper does not match the pinned review source")


spec = importlib.util.spec_from_file_location("agent_level_auto_evaluation_under_test", WRAPPER_PATH)
wrapper: Any = None
if WRAPPER_PATH.is_file():
    assert_reviewed_wrapper_bytes(WRAPPER_PATH)
    assert spec and spec.loader
    wrapper = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"run_conversation_review_cycle": fake_cycle}):
        spec.loader.exec_module(wrapper)


@unittest.skipUnless(WRAPPER_PATH.is_file(), "local Hermes Cron wrapper is not installed")
class CronWrapperTests(unittest.TestCase):
    def test_installed_wrapper_matches_pinned_review_source(self) -> None:
        assert_reviewed_wrapper_bytes(WRAPPER_PATH)

    def test_wrapper_hash_guard_rejects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drifted_copy = Path(tmp) / "agent-level-auto-evaluation.py"
            drifted_copy.write_bytes(WRAPPER_PATH.read_bytes() + b"\n# drift\n")
            with self.assertRaisesRegex(AssertionError, "does not match the pinned review source"):
                assert_reviewed_wrapper_bytes(drifted_copy)

    def _valid_pair(self, root: Path, ref: str = "abcdef123456") -> tuple[Path, dict, dict]:
        output_root = root / "output"
        report_dir = output_root / ref
        report_dir.mkdir(parents=True)
        record = {"evaluation_ref": ref, "marker": "trusted"}
        report = fake_cycle.evaluator.make_review_report(record)
        record_path = report_dir / "evaluation.json"
        record_path.write_text(json.dumps(record), encoding="utf-8")
        report_path = report_dir / "report.md"
        report_path.write_text(report, encoding="utf-8")
        result = {"status": "OK", "evaluation_ref": ref, "report": str(report_path)}
        return output_root, result, record

    def test_record_symlink_outside_output_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root, result, record = self._valid_pair(root)
            record_path = Path(result["report"]).with_name("evaluation.json")
            record_path.unlink()
            outside = root / "outside.json"
            outside.write_text(json.dumps(record), encoding="utf-8")
            record_path.symlink_to(outside)
            wrapper.OUTPUT_ROOT = output_root
            with self.assertRaises(ValueError):
                wrapper._load_success_report(result)

    def test_evaluation_ref_must_match_cycle_result_and_report_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root, result, _ = self._valid_pair(root)
            result["evaluation_ref"] = "different-ref"
            wrapper.OUTPUT_ROOT = output_root
            with self.assertRaises(ValueError):
                wrapper._load_success_report(result)

    def test_report_contents_must_match_evaluation_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root, result, _ = self._valid_pair(root)
            Path(result["report"]).write_text("stale or tampered report\n", encoding="utf-8")
            wrapper.OUTPUT_ROOT = output_root
            with self.assertRaises(ValueError):
                wrapper._load_success_report(result)

    def test_valid_report_and_record_pair_is_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root, result, record = self._valid_pair(root)
            wrapper.OUTPUT_ROOT = output_root
            report, loaded = wrapper._load_success_report(result)
            self.assertEqual(report, fake_cycle.evaluator.make_review_report(record))
            self.assertEqual(loaded, record)

    def test_symlinked_output_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root, result, _ = self._valid_pair(root)
            symlink_root = root / "output-link"
            symlink_root.symlink_to(output_root, target_is_directory=True)
            wrapper.OUTPUT_ROOT = symlink_root
            with self.assertRaisesRegex(ValueError, "approved local output directory"):
                wrapper._load_success_report(result)


if __name__ == "__main__":
    unittest.main()
