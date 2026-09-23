#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "run_shadow_evidence_guard.py"


class ShadowEvidenceGuardTests(unittest.TestCase):
    def run_guard(self, output: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(GUARD), "--output", str(output), *extra],
            text=True,
            capture_output=True,
        )

    def test_success_path_is_agent_independent_and_contract_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "shadow.jsonl"
            process = self.run_guard(output)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertIn("Shadow Evidence Guard: PASS", process.stdout)
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(records), 4)
            self.assertEqual({record["environment_class"] for record in records}, {"shadow"})

    def test_raw_body_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "shadow.jsonl"
            first = self.run_guard(output)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]
            records[0]["raw_body"] = "must-not-persist"
            output.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records) + "\n",
                encoding="utf-8",
            )
            second = self.run_guard(output, "--verify-only", "--start-index", "0")
            self.assertEqual(second.returncode, 1)
            self.assertIn("CONTRACT_FAIL", second.stdout)
            self.assertIn("raw response/body: 検出あり", second.stdout)

    def test_non_string_scenario_id_fails_with_contract_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "shadow.jsonl"
            first = self.run_guard(output)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]
            records[0]["scenario_id"] = []
            output.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records) + "\n",
                encoding="utf-8",
            )
            second = self.run_guard(output, "--verify-only", "--start-index", "0")
            self.assertEqual(second.returncode, 1)
            self.assertIn("CONTRACT_FAIL", second.stdout)
            self.assertIn("scenario IDs must be non-empty strings", second.stdout)

    def test_old_evaluator_id_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "shadow.jsonl"
            first = self.run_guard(output)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]
            records[0]["evaluator_configuration_id"] = "sha256:c30c928f4a91bd6c3cd8ea1df56fd3e32f67242b"
            output.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records) + "\n",
                encoding="utf-8",
            )
            second = self.run_guard(output, "--verify-only", "--start-index", "0")
            self.assertEqual(second.returncode, 1)
            self.assertIn("CONTRACT_FAIL", second.stdout)
            self.assertIn("evaluator_configuration_id", second.stdout)


if __name__ == "__main__":
    unittest.main()
