#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("response_validation", ROOT / "scripts" / "response_validation.py")
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load response_validation")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

STATUS_BLOCKED = module.STATUS_BLOCKED
STATUS_INCONCLUSIVE = module.STATUS_INCONCLUSIVE
STATUS_PASS = module.STATUS_PASS
validate_buffered_response = module.validate_buffered_response

RULES = {
    "required_patterns": ["根拠"],
    "forbidden_patterns": ["未確認の断定"],
}


class ResponseValidationTests(unittest.TestCase):
    def test_clean_draft_passes_and_allows_delivery(self):
        result = validate_buffered_response("根拠を確認しました。", RULES)
        self.assertEqual(result["status"], STATUS_PASS)
        self.assertTrue(result["delivery_allowed"])
        self.assertEqual(result["final_response"], "根拠を確認しました。")

    def test_invalid_draft_is_blocked_without_correction(self):
        result = validate_buffered_response("未確認の断定です。", RULES)
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertFalse(result["delivery_allowed"])
        self.assertIsNone(result["final_response"])

    def test_correction_is_revalidated_before_pass(self):
        result = validate_buffered_response(
            "未確認の断定です。",
            RULES,
            corrections=["根拠を確認しました。"],
        )
        self.assertEqual(result["status"], STATUS_PASS)
        self.assertTrue(result["delivery_allowed"])
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(result["attempts"][0]["validation"]["status"], STATUS_BLOCKED)
        self.assertEqual(result["attempts"][1]["validation"]["status"], STATUS_PASS)

    def test_invalid_validator_rule_is_inconclusive_and_blocked(self):
        result = validate_buffered_response(
            "回答",
            {"required_patterns": ["["], "forbidden_patterns": []},
        )
        self.assertEqual(result["status"], STATUS_INCONCLUSIVE)
        self.assertFalse(result["delivery_allowed"])

    def test_cli_e2e_never_delivers_unvalidated_draft(self):
        request = {
            "draft": "未確認の断定です。",
            "rules": RULES,
        }
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validated_agent_runner.py")],
            input=json.dumps(request), text=True, capture_output=True,
        )
        self.assertEqual(proc.returncode, 1)
        result = json.loads(proc.stdout)
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertFalse(result["delivery_allowed"])
        self.assertIsNone(result["final_response"])


if __name__ == "__main__":
    unittest.main()
