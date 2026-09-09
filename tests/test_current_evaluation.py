from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "evaluate_current_state", ROOT / "scripts" / "evaluate_current_state.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CurrentEvaluationTests(unittest.TestCase):
    def test_current_entrypoint_is_read_only_and_never_promotes(self) -> None:
        result = MODULE.evaluate(ROOT)

        self.assertEqual(result["mode"], "current_evidence_read_only")
        self.assertFalse(result["legacy_phase_execution"]["executed"])
        self.assertEqual(result["promotion"]["status"], "not_promoted")
        self.assertTrue(result["promotion"]["human_gate_required"])
        self.assertFalse(result["promotion"]["automatic_promotion"])

    def test_current_entrypoint_reports_cutover_blockers(self) -> None:
        result = MODULE.evaluate(ROOT)

        self.assertEqual(result["migration_status"], "ready_for_review")
        self.assertTrue(result["runtime_cutover_ready_for_review"])
        self.assertFalse(result["cron_cutover_allowed"])
        self.assertEqual(result["migration_blockers"], [])


if __name__ == "__main__":
    unittest.main()
