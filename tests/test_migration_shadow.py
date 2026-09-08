from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_migration_shadow", ROOT / "scripts" / "run_migration_shadow.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MigrationShadowTests(unittest.TestCase):
    def test_shadow_preserves_legacy_observation_without_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory) / "legacy"
            evidence = legacy / "execution-evidence/2.3"
            evidence.mkdir(parents=True)
            (evidence / "state.json").write_text(
                json.dumps({"status": "passed", "elapsed_days": 9, "novel_results": 7}),
                encoding="utf-8",
            )

            result = MODULE.run_shadow(legacy, ROOT)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["approval"], "pending")
        self.assertFalse(result["side_effects"]["legacy_executor_invoked"])
        self.assertFalse(result["side_effects"]["promotion_granted"])
        self.assertTrue(result["checks"]["cron_cutover_state_explicit"])


if __name__ == "__main__":
    unittest.main()
