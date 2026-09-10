#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
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
        "environment_class": "fixture",
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
    return value


class PromotionGateTests(unittest.TestCase):
    def test_missing_evidence_is_unassessed(self):
        with tempfile.TemporaryDirectory() as directory:
            result = promotion.assess(Path(directory))
        self.assertEqual(result["operational_level"], "unassessed")
        self.assertEqual(result["records_considered"], 0)

    def test_jsonl_evidence_ledger_is_considered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_dir = root / "operational-evidence"
            evidence_dir.mkdir()
            ledger = evidence_dir / "shadow.jsonl"
            ledger.write_text(
                "\n".join(json.dumps(evidence(1, cls)) for cls in ["S", "F", "X", "O", "R"]) + "\n",
                encoding="utf-8",
            )
            result = promotion.assess(root)
        self.assertEqual(result["records_considered"], 5)
        self.assertEqual(result["operational_level"], 1)
        self.assertEqual(result["levels"]["1"]["status"], "passed")

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
