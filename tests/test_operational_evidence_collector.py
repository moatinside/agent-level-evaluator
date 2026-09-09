#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

def load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

collector = load("collector", ROOT / "scripts" / "collect_operational_evidence.py")
validator = load("stage1", ROOT / "scripts" / "validate_stage1.py")

PRODUCER_BAD = ROOT / "tests" / "fixtures" / "producer_bad.py"
PRODUCER_GOOD = ROOT / "tests" / "fixtures" / "producer_good.py"
CORRECTOR = ROOT / "tests" / "fixtures" / "correction_agent.py"
RULES = {"required_patterns": ["根拠"], "forbidden_patterns": ["未確認の断定"]}
META = {
    "run_id": "collector-001",
    "level": 5,
    "capability_id": "self_reflection",
    "capability_contract_version": "1.0.0",
    "agent_configuration_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "evaluator_configuration_id": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "scenario_id": "level5-shadow-correction",
    "trigger_origin": "harness",
    "environment_class": "shadow",
    "started_at": "2026-09-06T03:00:00Z",
    "ended_at": "2026-09-06T03:00:01Z",
}


def run_agent(producer: Path, correction: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    cmd = [sys.executable, str(ROOT / "scripts" / "validated_command_runner.py"), "--producer", f"{sys.executable} {producer}"]
    if correction:
        cmd += ["--correction", f"{sys.executable} {correction}"]
    req = {"input": "検証", "rules": RULES}
    proc = subprocess.run(cmd, input=json.dumps(req), text=True, capture_output=True)
    return req, json.loads(proc.stdout)


class OperationalEvidenceCollectorTests(unittest.TestCase):
    def test_passed_run_is_metadata_only_and_schema_valid(self):
        request, result = run_agent(PRODUCER_BAD, CORRECTOR)
        record = collector.collect(request, result, META)
        self.assertEqual(record["evidence_class"], "O")
        self.assertEqual(record["result"], "passed")
        self.assertEqual(record["execution_mode"], "shadow")
        self.assertEqual(record["decision"], "passed")
        self.assertEqual(record["side_effect_status"], "not_attempted")
        self.assertEqual(record["acceptance_results"]["revalidation_count"], 1)
        serialized = json.dumps(record, ensure_ascii=False)
        self.assertNotIn("未確認の断定", serialized)
        self.assertNotIn("根拠を確認しました", serialized)
        self.assertEqual(validator.validate_evidence(record), [])

    def test_blocked_run_is_negative_evidence_and_schema_valid(self):
        request, result = run_agent(PRODUCER_GOOD, None)
        record = collector.collect(request, result, {**META, "run_id": "collector-002", "scenario_id": "level5-no-correction"})
        self.assertEqual(record["result"], "passed")
        request, result = run_agent(PRODUCER_BAD, None)
        record = collector.collect(request, result, {**META, "run_id": "collector-003", "scenario_id": "level5-safe-stop"})
        self.assertEqual(record["result"], "blocked")
        self.assertFalse(record["acceptance_results"]["delivery_allowed"])
        self.assertEqual(record["negative_evidence"][0]["type"], "safe-stop")
        self.assertEqual(validator.validate_evidence(record), [])

    def test_jsonl_append_is_idempotent(self):
        request, result = run_agent(PRODUCER_GOOD, None)
        record = collector.collect(request, result, META)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.jsonl"
            collector.append_record(path, record)
            collector.append_record(path, record)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["assessment_id"], record["assessment_id"])
    def test_concurrent_identical_append_is_idempotent(self):
        request, result = run_agent(PRODUCER_GOOD, None)
        record = collector.collect(request, result, META)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.jsonl"
            threads = [threading.Thread(target=collector.append_record, args=(path, record)) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
