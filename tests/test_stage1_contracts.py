#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
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


if __name__ == "__main__":
    unittest.main()
