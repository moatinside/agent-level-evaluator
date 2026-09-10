#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate_stage1", ROOT / "scripts" / "validate_stage1.py")
if spec is None or spec.loader is None:
    raise RuntimeError("could not load validate_stage1 module")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class Stage1ContractTests(unittest.TestCase):
    def test_contracts_have_all_levels_and_gates(self):
        self.assertEqual(module.validate_contracts(module.load_contracts()), [])

    def test_schema_is_valid_json(self):
        self.assertEqual(module.validate_schema_file(), [])

    def test_valid_evidence_fixture(self):
        path = ROOT / "tests" / "fixtures" / "evidence-valid.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(module.validate_evidence(record), [])

    def test_invalid_evidence_fixture_is_rejected(self):
        path = ROOT / "tests" / "fixtures" / "evidence-invalid.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        errors = module.validate_evidence(record)
        self.assertTrue(errors)
        self.assertTrue(any("integrity_hash" in error for error in errors))

    def test_jsonl_evidence_file_is_validated_record_by_record(self):
        fixture = ROOT / "tests" / "fixtures" / "evidence-valid.json"
        content = fixture.read_text(encoding="utf-8")
        record = json.loads(content)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as handle:
            handle.write(line + "\n" + line + "\n")
            handle.flush()
            self.assertEqual(module.load_evidence_records(Path(handle.name)), [record, record])

    def test_jsonl_evidence_reports_malformed_line(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as handle:
            handle.write("{}\nnot-json\n")
            handle.flush()
            with self.assertRaises(json.JSONDecodeError):
                module.load_evidence_records(Path(handle.name))

    def test_unknown_field_and_tampered_hash_are_rejected(self):
        path = ROOT / "tests" / "fixtures" / "evidence-valid.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["raw_response"] = "secret"
        self.assertTrue(any("unknown evidence fields" in error for error in module.validate_evidence(record)))
        record = json.loads(path.read_text(encoding="utf-8"))
        record["integrity_hash"] = "sha256:" + "0" * 64
        self.assertTrue(any("does not match" in error for error in module.validate_evidence(record)))
    def test_schema_field_types_and_reviewed_at_are_rejected(self):
        path = ROOT / "tests" / "fixtures" / "evidence-valid.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["expected_contract"] = [1]
        record["action_trace_ref"] = 1
        record["reviewed_at"] = "not-a-datetime"
        record["integrity_hash"] = "sha256:" + hashlib.sha256(
            json.dumps({k: v for k, v in record.items() if k != "integrity_hash"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        errors = module.validate_evidence(record)
        self.assertTrue(any("expected_contract" in error for error in errors))
        self.assertTrue(any("action_trace_ref" in error for error in errors))
        self.assertTrue(any("reviewed_at" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
