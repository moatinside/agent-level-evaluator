#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


quarantine = load("quarantine_invalid_evidence", ROOT / "scripts" / "quarantine_invalid_evidence.py")
promotion = load("promotion_gate_for_quarantine_tests", ROOT / "scripts" / "promotion_gate.py")


class EvidenceQuarantineTests(unittest.TestCase):
    @staticmethod
    def invalid_record() -> dict:
        return {"evidence_class": "O", "level": 5, "result": "passed"}

    def test_only_fully_invalid_file_is_moved_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "operational-evidence" / "shadow.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(
                "\n".join(json.dumps(self.invalid_record()) for _ in range(2)) + "\n",
                encoding="utf-8",
            )

            plan = quarantine.build_plan(root)
            self.assertEqual(len(plan), 1)
            self.assertEqual(plan[0]["record_count"], 2)
            manifest = quarantine.apply_plan(root, plan)

            destination = root / "evidence-quarantine" / "operational-evidence" / "shadow.jsonl"
            self.assertFalse(source.exists())
            self.assertTrue(destination.exists())
            self.assertEqual(manifest["summary"]["record_count"], 2)

            audit = promotion.audit_quarantine(root)
            self.assertEqual(audit["status"], "pass")
            self.assertEqual(audit["record_count"], 2)
            state = promotion.assess(root)
            self.assertEqual(state["records_considered"], 0)
            self.assertEqual(state["active_invalid_record_count"], 0)
            self.assertEqual(state["quarantined_historical_record_count"], 2)
            self.assertEqual(state["quarantine_audit_status"], "pass")

    def test_mixed_file_stays_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "operational-evidence" / "mixed.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps(self.invalid_record()) + "\n"
                + json.dumps({"note": "not an evidence record"}) + "\n",
                encoding="utf-8",
            )

            self.assertEqual(quarantine.build_plan(root), [])
            self.assertTrue(source.exists())

    def test_tampered_quarantine_file_fails_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "operational-evidence" / "shadow.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps(self.invalid_record()) + "\n", encoding="utf-8")
            quarantine.apply_plan(root, quarantine.build_plan(root))

            destination = root / "evidence-quarantine" / "operational-evidence" / "shadow.jsonl"
            destination.write_text(destination.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
            audit = promotion.audit_quarantine(root)
            self.assertEqual(audit["status"], "fail")
            self.assertTrue(any("hash mismatch" in error for error in audit["errors"]))


if __name__ == "__main__":
    unittest.main()
