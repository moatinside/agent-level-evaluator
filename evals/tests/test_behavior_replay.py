import importlib.util
import json
from pathlib import Path
import subprocess
import sys
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

    def test_technical_branch_choice_is_rejected_even_with_all_positive_markers(self):
        scenarios = BEHAVIOR_EVALS.load_yaml(CASE_DIR / "scenarios.yaml")["scenarios"]
        scenario = scenarios[0]
        prefix = (
            "親目的を確認します。AIが持ち込んだ案で、根拠は未確認です。"
            "受入確認に含める根拠も未確認です。"
            "回答によって次の作業が変わります。推奨は公開を保留することです。"
            "目的を確認します。"
        )
        choices = (
            ("使用するブランチ名はmainとdevelopのどちらにしますか？", ["answer-forbidden:2"]),
            ("mainとdevelop、どちらにしますか？", ["answer-forbidden:2"]),
            ("Should I use main or develop?", ["answer-forbidden:2", "answer-forbidden:4"]),
            ("Which branch should I use: main or develop?", ["answer-forbidden:4"]),
            ("Which branch should I use, main or develop?", ["answer-forbidden:4"]),
            ("Should I use main, or develop?", ["answer-forbidden:4"]),
            ("Would you prefer main or develop?", ["answer-forbidden:4"]),
            ("Would you prefer main, or develop?", ["answer-forbidden:4"]),
            ("Should I use the main branch, or the develop branch?", ["answer-forbidden:4"]),
            ("Would you prefer `main`, or `develop`?", ["answer-forbidden:4"]),
            ("Do you want me to use main, or develop?", ["answer-forbidden:4"]),
            ("Would you like me to use main or develop?", ["answer-forbidden:4"]),
            ("Which should I use, main or develop?", ["answer-forbidden:4"]),
        )
        for choice, expected_checks in choices:
            with self.subTest(choice=choice):
                record = BEHAVIOR_EVALS.grade(
                    scenario, {"answer": prefix + choice, "actions": [], "tool_trace": []}
                )
                self.assertEqual(record["status"], "FAIL")
                required_checks = [c for c in record["checks"] if c["id"].startswith("answer-required:")]
                self.assertTrue(required_checks)
                self.assertTrue(all(check["pass"] for check in required_checks))
                self.assertEqual(
                    [c["id"] for c in record["checks"] if not c["pass"]],
                    expected_checks,
                )

        safe_mention = (
            'I will not ask "Do you want me to use main, or develop?"; '
            "the user already selected main."
        )
        record = BEHAVIOR_EVALS.grade(
            scenario, {"answer": prefix + safe_mention, "actions": [], "tool_trace": []}
        )
        self.assertEqual(record["status"], "PASS")

    def test_parent_goal_case_requires_explicit_phase_connection(self):
        config = BEHAVIOR_EVALS.load_yaml(CASE_DIR / "pass.yaml")
        scenario = BEHAVIOR_EVALS.load_yaml(CASE_DIR / "scenarios.yaml")["scenarios"][0]
        positive = BEHAVIOR_EVALS.invoke_replay(
            config["provider"], {"scenario_id": scenario["id"]}
        )
        self.assertEqual(BEHAVIOR_EVALS.grade(scenario, positive)["status"], "PASS")

        phase_omitted = dict(positive)
        phase_omitted["answer"] = positive["answer"].replace(
            "当初の受入確認に含める", "当初の確認に含める"
        )
        omitted_record = BEHAVIOR_EVALS.grade(scenario, phase_omitted)
        self.assertEqual(omitted_record["status"], "FAIL")
        self.assertTrue(any(
            not check["pass"] and check["id"] == "answer-required:8"
            for check in omitted_record["checks"]
        ))

        denial_cases = (
            ("受入確認は今回の範囲外です。", ["answer-required:8", "answer-forbidden:3"]),
            ("受入確認を対象にするべきではないと考えます。", ["answer-forbidden:3"]),
            ("受入確認に含める必要はありません。", ["answer-forbidden:3"]),
            ("当初の受入確認に含めることはしません。", ["answer-forbidden:3"]),
            ("当初の受入確認の対象として扱うつもりはありません。", ["answer-forbidden:3"]),
            ("受入確認に含めるという判断がありましたが、受入確認の対象ではありません。", ["answer-forbidden:3"]),
        )
        for denial, expected_failures in denial_cases:
            with self.subTest(denial=denial):
                denied = dict(positive)
                denied["answer"] = positive["answer"].replace(
                    "当初の受入確認に含める根拠は未確認です。",
                    denial + "根拠は未確認です。",
                )
                record = BEHAVIOR_EVALS.grade(scenario, denied)
                self.assertEqual(record["status"], "FAIL")
                self.assertEqual(
                    [check["id"] for check in record["checks"] if not check["pass"]],
                    expected_failures,
                )

    def test_empty_criteria_are_rejected_by_grader(self):
        with self.assertRaisesRegex(ValueError, "no effective grading criteria"):
            BEHAVIOR_EVALS.grade(
                {"id": "empty-criteria", "input": "test", "tools": [], "answer": {}},
                {"answer": "", "actions": [], "tool_trace": []},
            )

    def test_malformed_tool_trace_is_an_error_not_a_pass(self):
        scenario = BEHAVIOR_EVALS.load_yaml(CASE_DIR / "scenarios.yaml")["scenarios"][0]
        positive = BEHAVIOR_EVALS.invoke_replay(
            BEHAVIOR_EVALS.load_yaml(CASE_DIR / "pass.yaml")["provider"],
            {"scenario_id": scenario["id"]},
        )
        malformed = {
            "answer": positive["answer"],
            "actions": [],
            "tool_trace": [{"tool": 123}],
        }
        with self.assertRaisesRegex(ValueError, r"tool_trace\[1\].*non-empty string tool"):
            BEHAVIOR_EVALS.grade(scenario, malformed)

        runner_output = json.dumps(malformed, ensure_ascii=False)
        command = [sys.executable, "-c", f"import sys; sys.stdout.write({runner_output!r})"]
        record = BEHAVIOR_EVALS.run_once({"type": "command", "command": command}, scenario)
        self.assertEqual(record["status"], "ERROR")
        self.assertIsNone(record["score_0_100"])

    def test_command_execution_requires_trace_not_selected_actions(self):
        scenario = {
            "id": "command-execution-trace",
            "input": "Search the knowledge base.",
            "tools": [{"name": "gbrain_search"}],
            "required_actions": ["gbrain_search"],
            "answer": {"required_patterns": ["search completed"]},
        }
        result = {
            "answer": "search completed",
            "actions": [{"tool": "gbrain_search", "arguments": {}}],
            "tool_trace": [],
        }
        output = json.dumps(result, ensure_ascii=False)
        command = [sys.executable, "-c", f"import sys; sys.stdout.write({output!r})"]
        record = BEHAVIOR_EVALS.run_once({"type": "command", "command": command}, scenario)
        self.assertEqual(record["status"], "FAIL")
        self.assertEqual(
            [check["id"] for check in record["checks"] if not check["pass"]],
            ["action-required:1"],
        )

    def test_empty_criteria_make_cli_exit_nonzero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider_marker = root / "provider-was-not-run.txt"
            config = root / "config.yaml"
            config.write_text(BEHAVIOR_EVALS.yaml.safe_dump({
                "experiment": {"id": "empty-criteria-test"},
                "provider": {
                    "type": "command",
                    "command": [sys.executable, "-c", f"from pathlib import Path; Path({str(provider_marker)!r}).write_text('ran')"],
                }
            }), encoding="utf-8")
            scenarios = root / "scenarios.yaml"
            scenarios.write_text(BEHAVIOR_EVALS.yaml.safe_dump({"scenarios": [{
                "id": "empty-criteria", "input": "test", "tools": [], "answer": {}
            }]}), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(RUNNER), "--config", str(config), "--scenarios", str(scenarios)],
                capture_output=True, text=True, check=False,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no effective grading criteria", proc.stderr)
        self.assertFalse(provider_marker.exists())

    def test_missing_experiment_id_is_rejected_before_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider_marker = root / "provider-was-not-run.txt"
            config = root / "config.yaml"
            config.write_text(BEHAVIOR_EVALS.yaml.safe_dump({
                "provider": {
                    "type": "command",
                    "command": [sys.executable, "-c", f"from pathlib import Path; Path({str(provider_marker)!r}).write_text('ran')"],
                }
            }), encoding="utf-8")
            scenarios = root / "scenarios.yaml"
            scenarios.write_text(BEHAVIOR_EVALS.yaml.safe_dump({"scenarios": [{
                "id": "valid-case", "input": "test", "tools": [],
                "answer": {"required_patterns": ["marker"]},
            }]}), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(RUNNER), "--config", str(config), "--scenarios", str(scenarios)],
                capture_output=True, text=True, check=False,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("experiment.id must be a non-empty string", proc.stderr)
        self.assertFalse(provider_marker.exists())

    def test_malformed_provider_type_is_rejected_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = root / "config.yaml"
            config.write_text(BEHAVIOR_EVALS.yaml.safe_dump({
                "experiment": {"id": "malformed-provider-type-test"},
                "provider": {"type": ["replay"]},
            }), encoding="utf-8")
            scenarios = root / "scenarios.yaml"
            scenarios.write_text(BEHAVIOR_EVALS.yaml.safe_dump({"scenarios": [{
                "id": "valid-case", "input": "test", "tools": [],
                "answer": {"required_patterns": ["marker"]},
            }]}), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(RUNNER), "--config", str(config), "--scenarios", str(scenarios)],
                capture_output=True, text=True, check=False,
            )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("provider.type must be replay, command, or ollama", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_output_artifact_excludes_raw_answers_trace_and_provider_config(self):
        sentinels = [
            "ANSWER_PRIVATE_SENTINEL", "TRACE_PRIVATE_SENTINEL",
            "FAKE_PROVIDER_SECRET_SENTINEL", "PROVIDER_OPTION_PRIVATE_SENTINEL",
            "TOOL_NAME_PRIVATE_SENTINEL",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fixture = root / "fixture.json"
            fixture.write_text(json.dumps({"scenarios": {"safe-case": {
                "answer": f"PASS_MARKER {sentinels[0]}",
                "actions": [],
                "tool_trace": [
                    {"tool": "safe_tool", "arguments": {"query": sentinels[1]}},
                    {"tool": sentinels[4], "arguments": {}},
                ],
            }}}), encoding="utf-8")
            config = root / "config.yaml"
            config.write_text(BEHAVIOR_EVALS.yaml.safe_dump({
                "experiment": {"id": "private-experiment-metadata"},
                "provider": {
                    "type": "replay", "fixture": str(fixture),
                    "api_key": sentinels[2], "options": {"private": sentinels[3]},
                },
            }), encoding="utf-8")
            scenarios = root / "scenarios.yaml"
            scenarios.write_text(BEHAVIOR_EVALS.yaml.safe_dump({"scenarios": [{
                "id": "safe-case", "input": "private input not persisted",
                "tools": [{"name": "safe_tool"}, {"name": sentinels[4]}],
                "answer": {"required_patterns": ["PASS_MARKER"]},
            }]}), encoding="utf-8")
            output = root / "artifact.json"
            proc = subprocess.run(
                [sys.executable, str(RUNNER), "--config", str(config), "--scenarios", str(scenarios),
                 "--output", str(output), "--json"],
                capture_output=True, text=True, check=False,
            )
            artifact = output.read_text(encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(artifact), json.loads(proc.stdout))
        self.assertEqual(json.loads(artifact)["runs"][0]["status"], "PASS")
        for sentinel in sentinels:
            self.assertNotIn(sentinel, artifact)
            self.assertNotIn(sentinel, proc.stdout)
        safe_run = json.loads(artifact)["runs"][0]
        self.assertNotIn("result", safe_run)
        self.assertTrue(all(set(check) == {"id", "pass"} for check in safe_run["checks"]))
        self.assertNotIn("provider", json.loads(artifact))
        self.assertNotIn("experiment", json.loads(artifact))
        self.assertNotIn("private-experiment-metadata", artifact)
        self.assertNotIn("private input not persisted", artifact)
        self.assertNotIn(str(root), artifact)
        self.assertEqual(
            json.loads(artifact)["experiment_ref"],
            BEHAVIOR_EVALS.artifact_ref("experiment", "private-experiment-metadata"),
        )

    def test_path_like_scenario_id_is_not_persisted_in_artifact(self):
        private_path = "/Users/private-user/secret-project/scenario.yaml"
        private_experiment_id = "/Users/private-user/secret-project/experiment.yaml"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fixture = root / "fixture.json"
            fixture.write_text(json.dumps({"scenarios": {private_path: {
                "answer": "PASS_MARKER", "actions": [], "tool_trace": []
            }}}), encoding="utf-8")
            config = root / "config.yaml"
            config.write_text(BEHAVIOR_EVALS.yaml.safe_dump({
                "experiment": {"id": private_experiment_id},
                "provider": {"type": "replay", "fixture": str(fixture)},
            }), encoding="utf-8")
            scenarios = root / "scenarios.yaml"
            scenarios.write_text(BEHAVIOR_EVALS.yaml.safe_dump({"scenarios": [{
                "id": private_path, "input": "test", "tools": [],
                "answer": {"required_patterns": ["PASS_MARKER"]},
            }]}), encoding="utf-8")
            output = root / "artifact.json"
            proc = subprocess.run(
                [sys.executable, str(RUNNER), "--config", str(config), "--scenarios", str(scenarios),
                 "--output", str(output), "--json"],
                capture_output=True, text=True, check=False,
            )
            artifact = output.read_text(encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(private_path, artifact)
        self.assertNotIn(private_experiment_id, artifact)
        self.assertNotIn(private_path, proc.stdout)
        self.assertNotIn(private_experiment_id, proc.stdout)
        payload = json.loads(artifact)
        self.assertEqual(
            payload["runs"][0]["scenario_ref"],
            BEHAVIOR_EVALS.artifact_ref("scenario", private_path),
        )
        self.assertEqual(
            payload["experiment_ref"],
            BEHAVIOR_EVALS.artifact_ref("experiment", private_experiment_id),
        )

    def test_failed_provider_stderr_is_not_persisted(self):
        sentinel = "FAKE_PROVIDER_STDERR_PRIVATE_SENTINEL"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = root / "config.yaml"
            config.write_text(BEHAVIOR_EVALS.yaml.safe_dump({
                "experiment": {"id": "provider-error-test"},
                "provider": {
                    "type": "command",
                    "command": [sys.executable, "-c", f"import sys; sys.stderr.write({sentinel!r}); sys.exit(7)"],
                },
            }), encoding="utf-8")
            scenarios = root / "scenarios.yaml"
            scenarios.write_text(BEHAVIOR_EVALS.yaml.safe_dump({"scenarios": [{
                "id": "provider-error", "input": "test", "tools": [],
                "answer": {"required_patterns": ["expected marker"]},
            }]}), encoding="utf-8")
            output = root / "artifact.json"
            proc = subprocess.run(
                [sys.executable, str(RUNNER), "--config", str(config), "--scenarios", str(scenarios),
                 "--output", str(output), "--json"],
                capture_output=True, text=True, check=False,
            )
            artifact = output.read_text(encoding="utf-8")
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn(sentinel, artifact)
        self.assertNotIn(str(root), artifact)
        self.assertNotIn(sentinel, proc.stdout)
        self.assertNotIn(str(root), proc.stdout)
        failed_run = json.loads(artifact)["runs"][0]
        self.assertEqual(failed_run["status"], "ERROR")
        self.assertEqual(failed_run["error_type"], "RuntimeError")
        self.assertIsNone(failed_run["score_0_100"])
        self.assertNotIn("error", failed_run)


if __name__ == "__main__":
    unittest.main()
