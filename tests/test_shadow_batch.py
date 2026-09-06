#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_shadow_batch.py"
CASES = ROOT / "tests" / "fixtures" / "shadow-cases.json"
GOOD = ROOT / "tests" / "fixtures" / "producer_good.py"
BAD = ROOT / "tests" / "fixtures" / "producer_bad.py"
CORRECTOR = ROOT / "tests" / "fixtures" / "correction_agent.py"


class ShadowBatchTests(unittest.TestCase):
    def test_batch_collects_all_statuses_without_raw_text(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "shadow.jsonl"
            command = [
                sys.executable, str(RUNNER),
                "--cases", str(CASES),
                "--output", str(output),
                "--producer-good", f"{sys.executable} {GOOD}",
                "--producer-bad", f"{sys.executable} {BAD}",
                "--correction", f"{sys.executable} {CORRECTOR}",
                "--agent-configuration-id", "sha256:" + "a" * 64,
                "--evaluator-configuration-id", "sha256:" + "b" * 64,
            ]
            process = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            summary = json.loads(process.stdout)
            self.assertEqual(summary["counts"], {"total": 4, "passed": 2, "blocked": 1, "inconclusive": 1, "failed": 0, "correction_runs": 1, "safe_stops": 2})
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 4)
            self.assertEqual({record["environment_class"] for record in records}, {"shadow"})
            self.assertEqual({record["evidence_class"] for record in records}, {"O"})
            serialized = output.read_text(encoding="utf-8")
            self.assertNotIn("根拠を確認しました", serialized)
            self.assertNotIn("未確認の断定", serialized)
            # Importing the project validator here keeps the check executable.
            import importlib.util
            spec = importlib.util.spec_from_file_location("stage1", ROOT / "scripts" / "validate_stage1.py")
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for record in records:
                self.assertEqual(module.validate_evidence(record), [])


if __name__ == "__main__":
    unittest.main()
