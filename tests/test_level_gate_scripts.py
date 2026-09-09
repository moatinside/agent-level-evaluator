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

def load(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

promotion = load("promotion_gate")
reclassify = load("reclassify_phase23")

HASH = "sha256:" + "a" * 64


def evidence(level: int, evidence_class: str) -> dict:
    value = {
        "schema_version": 1,
        "assessment_id": f"test-{level}-{evidence_class}",
        "level": level,
        "capability_id": "single_agent" if level == 1 else "self_reflection",
        "capability_contract_version": "1.0.0",
        "agent_configuration_id": HASH,
        "evaluator_configuration_id": HASH,
        "evidence_class": evidence_class,
        "scenario_id": f"scenario-{level}-{evidence_class}",
        "trigger_origin": "harness",
        "environment_class": "production-like",
        "started_at": "2026-09-06T00:00:00Z",
        "ended_at": "2026-09-06T00:00:01Z",
        "input_ref": "fixture-input",
        "expected_contract": ["contract-check"],
        "result": "passed",
        "acceptance_results": {"contract-check": "passed"},
        "reviewer": "deterministic",
        "integrity_hash": HASH,
    }
    if evidence_class == "O":
        value["action_trace_ref"] = "fixture-trace"
    value["integrity_hash"] = "sha256:" + hashlib.sha256(
        json.dumps({k: v for k, v in value.items() if k != "integrity_hash"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return value


class PromotionGateTests(unittest.TestCase):
    def test_missing_evidence_is_unassessed(self):
        with tempfile.TemporaryDirectory() as directory:
            result = promotion.assess(Path(directory))
        self.assertEqual(result["operational_level"], "unassessed")
        self.assertEqual(result["records_considered"], 0)

    def test_complete_level_one_evidence_promotes_only_level_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_dir = root / "operational-evidence"
            evidence_dir.mkdir()
            for cls in ["S", "F", "X", "O", "R"]:
                (evidence_dir / f"level1-{cls}.json").write_text(
                    json.dumps(evidence(1, cls)), encoding="utf-8"
                )
            result = promotion.assess(root)
        self.assertEqual(result["operational_level"], 1)
        self.assertEqual(result["levels"]["1"]["status"], "passed")

    def test_jsonl_is_loaded_and_duplicate_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_dir = root / "operational-evidence"
            evidence_dir.mkdir()
            record = evidence(1, "O")
            (evidence_dir / "shadow.jsonl").write_text(
                json.dumps(record) + "\n" + json.dumps(record) + "\nnot-json\n", encoding="utf-8"
            )
            result = promotion.assess(root)
        self.assertEqual(result["records_considered"], 1)
        self.assertEqual(result["records_duplicate"], 1)
        self.assertEqual(result["records_rejected"], 1)

    def test_conflicting_valid_records_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_dir = root / "operational-evidence"
            evidence_dir.mkdir()
            accepted = evidence(1, "O")
            conflict = dict(accepted)
            conflict["result"] = "blocked"
            conflict["integrity_hash"] = "sha256:" + hashlib.sha256(
                json.dumps({k: v for k, v in conflict.items() if k != "integrity_hash"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            (evidence_dir / "a.json").write_text(json.dumps(accepted), encoding="utf-8")
            (evidence_dir / "b.json").write_text(json.dumps(conflict), encoding="utf-8")
            result = promotion.assess(root)
        self.assertEqual(result["records_considered"], 0)
        self.assertEqual(result["records_conflict"], 1)
        self.assertEqual(result["records_rejected"], 1)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_dir = root / "operational-evidence"
            evidence_dir.mkdir()
            record = evidence(1, "O")
            record["environment_class"] = "shadow"
            record["integrity_hash"] = "sha256:" + hashlib.sha256(
                json.dumps({k: v for k, v in record.items() if k != "integrity_hash"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            (evidence_dir / "shadow.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
            result = promotion.assess(root)
            shadow_result = promotion.assess(root, {"shadow"})
        self.assertEqual(result["records_considered"], 0)
        self.assertEqual(result["records_excluded_environment"], 1)
        self.assertEqual(shadow_result["records_considered"], 1)

    def test_reclassification_does_not_promote(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            phase = root / "execution-evidence" / "2.3" / "runs"
            phase.mkdir(parents=True)
            (phase.parent / "state.json").write_text(json.dumps({"status": "passed"}), encoding="utf-8")
            (phase / "run.json").write_text(json.dumps({
                "date": "2026-09-06", "candidate": "predeclared", "novel": False,
                "verifiable": True,
            }), encoding="utf-8")
            result = reclassify.classify(root)
        self.assertFalse(result["promotion_eligible"])
        self.assertEqual(result["legacy_phase_status"], "passed")
        self.assertEqual(result["summary"]["duplicate_run_count"], 1)
        self.assertIn("N", result["records"][0]["evidence_classes"])

if __name__ == "__main__":
    unittest.main()
