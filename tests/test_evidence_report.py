#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("evidence_report", ROOT / "scripts" / "evidence_report.py")
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load evidence_report")
report_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report_module)


def record(environment: str) -> dict:
    value = json.loads((ROOT / "tests" / "fixtures" / "evidence-valid.json").read_text(encoding="utf-8"))
    value["assessment_id"] = f"report-{environment}"
    value["environment_class"] = environment
    value["integrity_hash"] = "sha256:" + hashlib.sha256(
        json.dumps({k: v for k, v in value.items() if k != "integrity_hash"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return value


class EvidenceReportTests(unittest.TestCase):
    def test_default_report_excludes_shadow_and_list_contains_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "operational-evidence"
            folder.mkdir()
            fixture = record("production-like")
            shadow = record("shadow")
            (folder / "records.jsonl").write_text(json.dumps(fixture) + "\n" + json.dumps(shadow) + "\n", encoding="utf-8")
            result = report_module.report(root)
        self.assertEqual(result["stats"]["records_considered"], 1)
        self.assertEqual(result["stats"]["records_excluded_environment"], 1)
        self.assertEqual(result["stats"]["records_rejected"], 0)

    def test_cli_shadow_records_require_explicit_environment_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "operational-evidence"
            folder.mkdir()
            shadow = record("shadow")
            (folder / "shadow.jsonl").write_text(json.dumps(shadow) + "\n", encoding="utf-8")

            default_stdout = StringIO()
            with patch.object(sys, "argv", ["evidence_report.py", "--root", str(root), "--list"]):
                with redirect_stdout(default_stdout):
                    default_status = report_module.main()

            shadow_stdout = StringIO()
            with patch.object(
                sys,
                "argv",
                ["evidence_report.py", "--root", str(root), "--list", "--environment-class", "shadow"],
            ):
                with redirect_stdout(shadow_stdout):
                    shadow_status = report_module.main()

        default_result = json.loads(default_stdout.getvalue())
        shadow_result = json.loads(shadow_stdout.getvalue())
        self.assertEqual(default_status, 0)
        self.assertEqual(default_result["stats"]["records_considered"], 0)
        self.assertEqual(default_result["stats"]["records_excluded_environment"], 1)
        self.assertEqual(shadow_status, 0)
        self.assertEqual(shadow_result["stats"]["records_considered"], 1)
        self.assertEqual(shadow_result["records"][0]["assessment_id"], shadow["assessment_id"])

    def test_report_uses_gate_validation_for_showable_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "operational-evidence"
            folder.mkdir()
            source = record("production-like")
            (folder / "record.jsonl").write_text(json.dumps(source) + "\n", encoding="utf-8")
            result = report_module.report(root)
        self.assertEqual(result["stats"]["records_considered"], 1)
        self.assertEqual(result["records"][0]["assessment_id"], source["assessment_id"])


if __name__ == "__main__":
    unittest.main()
