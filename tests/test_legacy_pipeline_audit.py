from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_legacy_pipeline", ROOT / "scripts" / "audit_legacy_pipeline.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LegacyPipelineAuditTests(unittest.TestCase):
    def test_legacy_phase_blocks_cutover_even_when_evidence_gate_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "contracts").mkdir()
            (root / "docs").mkdir()
            (root / "CHECKPOINTS.md").write_text("## Phase 2\n### 2.3 Open Loop\n", encoding="utf-8")
            (root / "scripts/progression_runner.py").write_text(
                'if checkpoint not in {"2.1", "2.2", "2.3"}:\n', encoding="utf-8"
            )
            (root / "contracts/level-contracts.yaml").write_text("levels: []\n", encoding="utf-8")
            (root / "scripts/promotion_gate.py").write_text("# gate\n", encoding="utf-8")
            (root / "docs/decision-log.md").write_text(
                "Phase進捗とOperational Levelが分離されている。\n", encoding="utf-8"
            )

            result = MODULE.audit(root)

        self.assertEqual(result["migration_status"], "blocked")
        self.assertFalse(result["cron_cutover_allowed"])
        self.assertIn("legacy_progression_runner_registered", result["blockers"])

    def test_clean_evidence_gate_can_be_cutover_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "contracts").mkdir()
            (root / "docs").mkdir()
            (root / "contracts/level-contracts.yaml").write_text("levels: []\n", encoding="utf-8")
            (root / "scripts/promotion_gate.py").write_text("# gate\n", encoding="utf-8")
            (root / "docs/decision-log.md").write_text(
                "Phase進捗とOperational Levelが分離されている。\n", encoding="utf-8"
            )
            (root / "migration").mkdir()
            (root / "migration/shadow-validation-approval.json").write_text(
                '{"status":"passed","approval":"explicit"}\n', encoding="utf-8"
            )

            result = MODULE.audit(root)

        self.assertEqual(result["migration_status"], "ready_for_runtime_cutover")
        self.assertTrue(result["cron_cutover_allowed"])
        self.assertEqual(result["blockers"], [])


if __name__ == "__main__":
    unittest.main()
