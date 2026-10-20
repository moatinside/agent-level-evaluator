import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


RUNNER = Path(__file__).resolve().parents[1] / "run_behavior_evals.py"
CASE_DIR = Path(__file__).resolve().parents[1] / "behavior" / "decision-context-gate"
SPEC = importlib.util.spec_from_file_location("run_behavior_evals", RUNNER)
assert SPEC is not None and SPEC.loader is not None
BEHAVIOR_EVALS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BEHAVIOR_EVALS)


class ReplayFixtureTests(unittest.TestCase):
    def invoke(self, fixture_data, scenario_id="case-a"):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture.json"
            fixture.write_text(json.dumps(fixture_data), encoding="utf-8")
            return BEHAVIOR_EVALS.invoke_replay(
                {"fixture": str(fixture)}, {"scenario_id": scenario_id}
            )

    def grade_config(self, config_name):
        config = BEHAVIOR_EVALS.load_yaml(CASE_DIR / config_name)
        scenario_doc = BEHAVIOR_EVALS.load_yaml(CASE_DIR / "scenarios.yaml")
        return [
            BEHAVIOR_EVALS.grade(
                scenario,
                BEHAVIOR_EVALS.invoke_replay(
                    config["provider"], {"scenario_id": scenario["id"]}
                ),
            )
            for scenario in scenario_doc["scenarios"]
        ]

    def test_mapped_fixture_selects_requested_case(self):
        result = self.invoke({
            "scenarios": {
                "case-a": {"answer": "A", "actions": []},
                "case-b": {"answer": "B", "actions": []},
            }
        }, "case-b")
        self.assertEqual(result["answer"], "B")
        self.assertEqual(result["actions"], [])

    def test_legacy_single_result_fixture_remains_supported(self):
        result = self.invoke({"answer": "legacy", "actions": [], "tool_trace": []})
        self.assertEqual(result["answer"], "legacy")

    def test_missing_scenario_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no result for scenario"):
            self.invoke({"scenarios": {"other": {"answer": "x"}}})

    def test_independent_positive_cases_pass_the_gate(self):
        records = self.grade_config("pass.yaml")
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record["status"] == "PASS" for record in records))

    def test_negative_controls_are_rejected_for_gate_failures(self):
        records = self.grade_config("negative.yaml")
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record["status"] == "FAIL" for record in records))
        self.assertTrue(all(any(not check["pass"] for check in record["checks"])
                            for record in records))


if __name__ == "__main__":
    unittest.main()
