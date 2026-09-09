#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

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
