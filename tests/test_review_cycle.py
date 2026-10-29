from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("run_conversation_review_cycle", ROOT / "scripts" / "run_conversation_review_cycle.py")
assert spec and spec.loader
cycle = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cycle
spec.loader.exec_module(cycle)


def make_db(path: Path, now: float) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE sessions (id TEXT, ended_at REAL, source TEXT, chat_type TEXT, display_name TEXT, profile_name TEXT, hidden INTEGER, archived INTEGER, chat_id TEXT)")
        conn.execute("CREATE TABLE messages (id INTEGER, session_id TEXT, role TEXT, content TEXT, timestamp REAL, active INTEGER)")
        conn.execute("INSERT INTO sessions VALUES ('session-secret-id', ?, 'discord', 'group', ?, 'default', 0, 0, ?)", (now - 10, cycle.selector.ALLOWLIST[0], next(iter(cycle.selector.ALLOWED_CHANNEL_IDS))))
        conn.execute("INSERT INTO messages VALUES (1, 'session-secret-id', 'user', 'question', ?, 1)", (now - 12,))
        conn.execute("INSERT INTO messages VALUES (2, 'session-secret-id', 'assistant', 'answer', ?, 1)", (now - 11,))


def make_valid_record(evaluation_ref: str) -> dict[str, object]:
    evidence = {"position": 1, "start": 0, "end": 8, "role": "user", "excerpt": "question"}
    return {
        "schema_version": 2,
        "evaluation_ref": evaluation_ref,
        "input_hash": "sha256:" + "a" * 64,
        "created_at": "2026-10-28T00:00:00+00:00",
        "evaluator": {"name": "Claude Code", "model_id": "fixture", "configuration": "safe-mode"},
        "rubric_hash": "sha256:" + "b" * 64,
        "input": {
            "message_count": 2, "active_only": True, "tool_results_omitted": True,
            "max_message_chars": cycle.evaluator.MAX_CONTENT_CHARS,
            "truncated_positions": [], "tool_result_positions": [], "metadata_positions": [],
            "summary_positions": [], "summary_detection": "role_only", "transcript_saved": False,
        },
        "axes": [
            {"axis": name, "status": "partial", "reason": "fixture reason", "evidence_positions": [1], "evidence_spans": [dict(evidence)]}
            for name in cycle.evaluator.AXES
        ],
        "trajectory": {
            "question_initial": {"summary": "initial question", "evidence_spans": [dict(evidence)], "unobservable_reason": None},
            "question_current": {"summary": "current question", "evidence_spans": [dict(evidence)], "unobservable_reason": None},
            "question_changes": [],
        },
        "human_review": {"review_status": "pending"},
    }


def make_evaluator_result(
    output_root: Path,
    *,
    evaluation_ref: str,
    evaluation_path_ref: str | None = None,
    report_path_ref: str | None = None,
    changes: int = 0,
    record_override: dict[str, object] | None = None,
    report_override: str | None = None,
) -> dict[str, object]:
    evaluation_path_ref = evaluation_path_ref or evaluation_ref
    report_path_ref = report_path_ref or evaluation_ref
    record = record_override if record_override is not None else make_valid_record(evaluation_ref)
    try:
        report = report_override if report_override is not None else cycle.evaluator.make_review_report(record)
    except (KeyError, TypeError):
        report = "# invalid fixture report\n"
    for ref in {evaluation_path_ref, report_path_ref}:
        artifact_dir = output_root / ref
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "evaluation.json").write_text(json.dumps(record) + "\n", encoding="utf-8")
        (artifact_dir / "report.md").write_text(report, encoding="utf-8")
    return {
        "status": "OK",
        "evaluation_ref": evaluation_ref,
        "evaluation": str(output_root / evaluation_path_ref / "evaluation.json"),
        "report": str(output_root / report_path_ref / "report.md"),
        "axes": 6,
        "changes": changes,
    }


class ReviewCycleTests(unittest.TestCase):
    def test_dry_run_selects_candidate_without_writing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = 2_000_000_000.0
            db, state = root / "state.db", root / "automation" / "state.sqlite3"
            make_db(db, now)
            output = io.StringIO()
            with redirect_stdout(output):
                result = cycle.run_cycle(db_path=db, state_path=state, output_root=root / "output", now_epoch=now, dry_run=True)
            self.assertEqual(result, 0)
            self.assertIn('"status": "DRY_RUN"', output.getvalue())
            self.assertNotIn("session-secret-id", output.getvalue())
            self.assertFalse(state.exists())

    def test_new_format_execution_uses_shared_daily_ledger_and_dedupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = 2_000_000_000.0
            db, state, output_root = root / "state.db", root / "automation" / "state.sqlite3", root / "output"
            make_db(db, now)
            output = io.StringIO()
            expected_ref = cycle.selector.session_ref("session-secret-id")[:12]
            result_value = make_evaluator_result(output_root, evaluation_ref=expected_ref, changes=1)
            with patch.object(cycle.evaluator, "evaluate_session", return_value=result_value) as evaluate, redirect_stdout(output):
                status = cycle.run_cycle(db_path=db, state_path=state, output_root=output_root, now_epoch=now)
            self.assertEqual(status, 0)
            self.assertEqual(evaluate.call_count, 1)
            self.assertNotIn("session-secret-id", output.getvalue())
            self.assertEqual(cycle.selector.attempts_today(state, now), 1)
            self.assertEqual(len(cycle.selector.load_processed_refs(state)), 1)
            output.truncate(0)
            output.seek(0)
            with patch.object(cycle.evaluator, "evaluate_session") as second, redirect_stdout(output):
                second_status = cycle.run_cycle(db_path=db, state_path=state, output_root=output_root, now_epoch=now)
            self.assertEqual(second_status, 0)
            second.assert_not_called()
            self.assertIn('"status": "DAILY_CAP"', output.getvalue())

    def test_evaluator_artifact_binding_rejects_reference_and_path_mismatches(self):
        cases = ("evaluation_ref", "evaluation_path", "report_path")
        for mismatch in cases:
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                now = 2_000_000_000.0
                db, state, output_root = root / "state.db", root / "automation" / "state.sqlite3", root / "output"
                make_db(db, now)
                expected_ref = cycle.selector.session_ref("session-secret-id")[:12]
                other_ref = "0" * 12 if expected_ref != "0" * 12 else "1" * 12
                result_ref = other_ref if mismatch == "evaluation_ref" else expected_ref
                evaluation_path_ref = other_ref if mismatch in {"evaluation_ref", "evaluation_path"} else expected_ref
                report_path_ref = other_ref if mismatch in {"evaluation_ref", "report_path"} else expected_ref
                result_value = make_evaluator_result(
                    output_root,
                    evaluation_ref=result_ref,
                    evaluation_path_ref=evaluation_path_ref,
                    report_path_ref=report_path_ref,
                    changes=1,
                )
                output = io.StringIO()
                with patch.object(cycle.evaluator, "evaluate_session", return_value=result_value), redirect_stdout(output):
                    status = cycle.run_cycle(db_path=db, state_path=state, output_root=output_root, now_epoch=now)
                self.assertEqual(status, 1)
                notice = json.loads(output.getvalue())
                self.assertEqual(notice["status"], "EVALUATION_FAILED")
                self.assertEqual((notice["error_phase"], notice["error_code"]), ("result_validation", "incomplete_evaluator_result"))
                self.assertIs(notice["daily_cap_consumed"], True)
                with sqlite3.connect(state) as conn:
                    attempt = conn.execute("SELECT status, error_phase, error_code FROM attempts").fetchone()
                self.assertEqual(attempt, ("failed", "result_validation", "incomplete_evaluator_result"))
                self.assertEqual(cycle.selector.load_processed_refs(state), set())

    def test_cycle_rejects_invalid_record_reference_or_report_before_success(self):
        for mismatch in ("schema", "record_reference", "report"):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                now = 2_000_000_000.0
                db, state, output_root = root / "state.db", root / "automation" / "state.sqlite3", root / "output"
                make_db(db, now)
                expected_ref = cycle.selector.session_ref("session-secret-id")[:12]
                other_ref = "0" * 12 if expected_ref != "0" * 12 else "1" * 12
                record = make_valid_record(expected_ref)
                report_override = None
                if mismatch == "schema":
                    record["axes"] = []
                elif mismatch == "record_reference":
                    record["evaluation_ref"] = other_ref
                else:
                    report_override = "stale report content\n"
                result_value = make_evaluator_result(
                    output_root,
                    evaluation_ref=expected_ref,
                    record_override=record,
                    report_override=report_override,
                )
                output = io.StringIO()
                with patch.object(cycle.evaluator, "evaluate_session", return_value=result_value), redirect_stdout(output):
                    status = cycle.run_cycle(db_path=db, state_path=state, output_root=output_root, now_epoch=now)
                self.assertEqual(status, 1)
                notice = json.loads(output.getvalue())
                self.assertEqual((notice["status"], notice["error_phase"], notice["error_code"]),
                                 ("EVALUATION_FAILED", "result_validation", "incomplete_evaluator_result"))
                with sqlite3.connect(state) as conn:
                    attempt = conn.execute("SELECT status FROM attempts").fetchone()
                self.assertEqual(attempt, ("failed",))
                self.assertEqual(cycle.selector.load_processed_refs(state), set())

    def test_cycle_rejects_symlinked_output_root_before_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = 2_000_000_000.0
            db, state = root / "state.db", root / "automation" / "state.sqlite3"
            make_db(db, now)
            actual_root = root / "actual-output"
            actual_root.mkdir()
            output_root = root / "output-link"
            output_root.symlink_to(actual_root, target_is_directory=True)
            expected_ref = cycle.selector.session_ref("session-secret-id")[:12]
            result_value = make_evaluator_result(output_root, evaluation_ref=expected_ref)
            output = io.StringIO()
            with patch.object(cycle.evaluator, "evaluate_session", return_value=result_value), redirect_stdout(output):
                status = cycle.run_cycle(db_path=db, state_path=state, output_root=output_root, now_epoch=now)
            self.assertEqual(status, 1)
            self.assertEqual(json.loads(output.getvalue())["status"], "EVALUATION_FAILED")
            self.assertEqual(cycle.selector.load_processed_refs(state), set())

    def test_failed_provider_attempt_consumes_shared_daily_cap_without_leaking_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = 2_000_000_000.0
            db, state = root / "state.db", root / "automation" / "state.sqlite3"
            make_db(db, now)
            output = io.StringIO()
            sensitive_error = cycle.evaluator.EvaluationFailure("provider_response", "provider_timeout")
            sensitive_error.detail = "private conversation detail"
            with patch.object(cycle.evaluator, "evaluate_session", side_effect=sensitive_error) as evaluate, redirect_stdout(output):
                status = cycle.run_cycle(db_path=db, state_path=state, output_root=root / "output", now_epoch=now)
            self.assertEqual(status, 1)
            self.assertEqual(evaluate.call_count, 1)
            self.assertIn('"daily_cap_consumed": true', output.getvalue())
            self.assertIn('"error_phase": "provider_response"', output.getvalue())
            self.assertIn('"error_code": "provider_timeout"', output.getvalue())
            self.assertNotIn("private conversation detail", output.getvalue())
            self.assertEqual(cycle.selector.attempts_today(state, now), 1)
            with sqlite3.connect(state) as conn:
                row = conn.execute("SELECT status, error_phase, error_code FROM attempts").fetchone()
            self.assertEqual(row, ("failed", "provider_response", "provider_timeout"))
            self.assertEqual(cycle._safe_failure(RuntimeError("private error")), ("unknown", "unknown_failure"))
            retry_output = io.StringIO()
            with patch.object(cycle.evaluator, "evaluate_session") as retry, redirect_stdout(retry_output):
                retry_status = cycle.run_cycle(db_path=db, state_path=state, output_root=root / "output", now_epoch=now)
            self.assertEqual(retry_status, 0)
            retry.assert_not_called()
            self.assertIn('"status": "DAILY_CAP"', retry_output.getvalue())

    def test_no_candidate_and_locked_paths_do_not_consume_daily_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = 2_000_000_000.0
            db, state = root / "state.db", root / "automation" / "state.sqlite3"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE sessions (id TEXT, ended_at REAL, source TEXT, chat_type TEXT, display_name TEXT, profile_name TEXT, hidden INTEGER, archived INTEGER, chat_id TEXT)")
                conn.execute("CREATE TABLE messages (id INTEGER, session_id TEXT, role TEXT, content TEXT, timestamp REAL, active INTEGER)")
            output = io.StringIO()
            with redirect_stdout(output):
                status = cycle.run_cycle(db_path=db, state_path=state, output_root=root / "output", now_epoch=now)
            self.assertEqual(status, 0)
            self.assertIn('"status": "NO_CANDIDATE"', output.getvalue())
            self.assertEqual(cycle.selector.attempts_today(state, now), 0)

            output = io.StringIO()
            with patch.object(cycle.fcntl, "flock", side_effect=BlockingIOError), redirect_stdout(output):
                status = cycle.run_cycle(db_path=db, state_path=state, output_root=root / "output", now_epoch=now + 86_400)
            self.assertEqual(status, 0)
            self.assertIn('"status": "LOCKED"', output.getvalue())
            self.assertEqual(cycle.selector.attempts_today(state, now + 86_400), 0)

            output = io.StringIO()
            with patch.object(cycle.fcntl, "flock", side_effect=OSError("PRIVATE_LOCK_DETAIL")), redirect_stdout(output):
                status = cycle.run_cycle(db_path=db, state_path=state, output_root=root / "output", now_epoch=now + 2 * 86_400)
            self.assertEqual(status, 1)
            self.assertIn('"error_phase": "lock"', output.getvalue())
            self.assertIn('"error_code": "lock_unavailable"', output.getvalue())
            self.assertNotIn("PRIVATE_LOCK_DETAIL", output.getvalue())
            self.assertEqual(cycle.selector.attempts_today(state, now + 2 * 86_400), 0)

    def test_fake_provider_failure_flows_through_cycle_to_safe_ledger_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = 2_000_000_000.0
            db, state = root / "state.db", root / "automation" / "state.sqlite3"
            fake_cli = root / "fake-claude"
            make_db(db, now)
            fake_cli.write_text(
                f"#!{sys.executable}\nimport sys\nsys.stdin.read()\nsys.stderr.write('PRIVATE_PROVIDER_STDERR_CANARY')\nraise SystemExit(9)\n",
                encoding="utf-8",
            )
            fake_cli.chmod(0o700)
            output = io.StringIO()
            with redirect_stdout(output):
                status = cycle.run_cycle(db_path=db, state_path=state, output_root=root / "output", now_epoch=now, claude_path=str(fake_cli))
            self.assertEqual(status, 1)
            self.assertNotIn("PRIVATE_PROVIDER_STDERR_CANARY", output.getvalue())
            self.assertIn('"error_phase": "provider_response"', output.getvalue())
            self.assertIn('"error_code": "provider_nonzero_exit"', output.getvalue())
            with sqlite3.connect(state) as conn:
                row = conn.execute("SELECT status, error_phase, error_code FROM attempts").fetchone()
            self.assertEqual(row, ("failed", "provider_response", "provider_nonzero_exit"))
            self.assertEqual(cycle.selector.attempts_today(state, now), 1)

    def test_candidate_scan_errors_are_sanitized_without_consuming_daily_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = 2_000_000_000.0
            db, state = root / "state.db", root / "automation" / "state.sqlite3"
            make_db(db, now)
            output = io.StringIO()
            with patch.object(cycle.selector, "select_candidate", side_effect=RuntimeError("PRIVATE_SCAN_DETAIL")), redirect_stdout(output):
                status = cycle.run_cycle(db_path=db, state_path=state, output_root=root / "output", now_epoch=now)
            self.assertEqual(status, 1)
            self.assertIn('"error_phase": "candidate_scan"', output.getvalue())
            self.assertIn('"error_code": "candidate_scan_failed"', output.getvalue())
            self.assertNotIn("PRIVATE_SCAN_DETAIL", output.getvalue())
            self.assertEqual(cycle.selector.attempts_today(state, now), 0)

    def test_reservation_exception_reads_back_whether_daily_cap_was_consumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = 2_000_000_000.0
            db, state = root / "state.db", root / "automation" / "state.sqlite3"
            make_db(db, now)
            original_reserve = cycle.selector._reserve_attempt

            def reserve_then_raise(*args, **kwargs):
                original_reserve(*args, **kwargs)
                raise OSError("PRIVATE_POST_COMMIT_DETAIL")

            output = io.StringIO()
            with patch.object(cycle.selector, "_reserve_attempt", side_effect=reserve_then_raise), patch.object(cycle.evaluator, "evaluate_session") as evaluate, redirect_stdout(output):
                status = cycle.run_cycle(db_path=db, state_path=state, output_root=root / "output", now_epoch=now)

            self.assertEqual(status, 1)
            evaluate.assert_not_called()
            notice = json.loads(output.getvalue())
            self.assertEqual(notice["daily_cap_consumed"], True)
            self.assertNotIn("PRIVATE_POST_COMMIT_DETAIL", output.getvalue())
            with sqlite3.connect(state) as conn:
                row = conn.execute("SELECT status FROM attempts").fetchone()
            self.assertEqual(row, ("running",))
            self.assertEqual(cycle.selector.attempts_today(state, now), 1)

    def test_reservation_error_with_unavailable_readback_reports_unknown_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = 2_000_000_000.0
            db, state = root / "state.db", root / "automation" / "state.sqlite3"
            make_db(db, now)
            original_reserve = cycle.selector._reserve_attempt

            def reserve_then_raise(*args, **kwargs):
                original_reserve(*args, **kwargs)
                raise OSError("PRIVATE_POST_COMMIT_DETAIL")

            output = io.StringIO()
            with patch.object(cycle.selector, "_reserve_attempt", side_effect=reserve_then_raise), patch.object(cycle.selector, "attempts_today", side_effect=[0, sqlite3.OperationalError("PRIVATE_READBACK_DETAIL")]), patch.object(cycle.evaluator, "evaluate_session") as evaluate, redirect_stdout(output):
                status = cycle.run_cycle(db_path=db, state_path=state, output_root=root / "output", now_epoch=now)

            self.assertEqual(status, 1)
            evaluate.assert_not_called()
            notice = json.loads(output.getvalue())
            self.assertIsNone(notice["daily_cap_consumed"])
            failure_text = cycle.format_failure_notice(notice)
            self.assertIn("日次試行枠の消費状態は確認できません", failure_text)
            self.assertNotIn("PRIVATE_", output.getvalue() + failure_text)
            self.assertEqual(cycle.selector.attempts_today(state, now), 1)

    def test_pre_reservation_state_errors_report_unknown_daily_cap(self):
        for failure_point in ("state_directory", "lock_open", "lock_flock", "schema", "state_read"):
            with self.subTest(failure_point=failure_point), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                now = 2_000_000_000.0
                db, state = root / "state.db", root / "automation" / "state.sqlite3"
                make_db(db, now)
                output = io.StringIO()
                patches = []
                if failure_point == "state_directory":
                    original = cycle.Path.mkdir
                    def fail_mkdir(path, *args, **kwargs):
                        if path == state.parent:
                            raise OSError("PRIVATE_STATE_DIRECTORY")
                        return original(path, *args, **kwargs)
                    patches.append(patch.object(cycle.Path, "mkdir", autospec=True, side_effect=fail_mkdir))
                elif failure_point == "lock_open":
                    original = cycle.Path.open
                    lock_path = state.with_suffix(".lock")
                    def fail_open(path, *args, **kwargs):
                        if path == lock_path:
                            raise OSError("PRIVATE_LOCK_OPEN")
                        return original(path, *args, **kwargs)
                    patches.append(patch.object(cycle.Path, "open", autospec=True, side_effect=fail_open))
                elif failure_point == "lock_flock":
                    patches.append(patch.object(cycle.fcntl, "flock", side_effect=OSError("PRIVATE_FLOCK")))
                elif failure_point == "schema":
                    patches.append(patch.object(cycle.selector, "ensure_state_schema", side_effect=OSError("PRIVATE_SCHEMA")))
                else:
                    patches.append(patch.object(cycle.selector, "attempts_today", side_effect=sqlite3.OperationalError("PRIVATE_STATE_READ")))
                with ExitStack() as stack:
                    for item in patches:
                        stack.enter_context(item)
                    with patch.object(cycle.evaluator, "evaluate_session") as evaluate, redirect_stdout(output):
                        status = cycle.run_cycle(db_path=db, state_path=state, output_root=root / "output", now_epoch=now)
                self.assertEqual(status, 1)
                evaluate.assert_not_called()
                notice = json.loads(output.getvalue())
                self.assertIsNone(notice["daily_cap_consumed"])
                self.assertNotIn("PRIVATE_", output.getvalue())

    def test_evaluator_non_ok_status_is_not_recorded_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = 2_000_000_000.0
            db, state, output_root = root / "state.db", root / "automation" / "state.sqlite3", root / "output"
            make_db(db, now)
            invalid_result = {"status": "PENDING", "evaluation_ref": "abcdef123456", "evaluation": str(output_root / "abcdef123456" / "evaluation.json"), "report": str(output_root / "abcdef123456" / "report.md"), "axes": 6, "changes": 0}
            output = io.StringIO()
            with patch.object(cycle.evaluator, "evaluate_session", return_value=invalid_result), redirect_stdout(output):
                status = cycle.run_cycle(db_path=db, state_path=state, output_root=output_root, now_epoch=now)
            self.assertEqual(status, 1)
            notice = json.loads(output.getvalue())
            self.assertEqual(notice["status"], "EVALUATION_FAILED")
            self.assertEqual((notice["error_phase"], notice["error_code"]), ("result_validation", "incomplete_evaluator_result"))
            self.assertIs(notice["daily_cap_consumed"], True)
            with sqlite3.connect(state) as conn:
                row = conn.execute("SELECT status, error_phase, error_code FROM attempts").fetchone()
            self.assertEqual(row, ("failed", "result_validation", "incomplete_evaluator_result"))
            self.assertEqual(cycle.selector.load_processed_refs(state), set())

    def test_successful_evaluation_but_failed_ledger_write_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = 2_000_000_000.0
            db, state, output_root = root / "state.db", root / "automation" / "state.sqlite3", root / "output"
            make_db(db, now)
            expected_ref = cycle.selector.session_ref("session-secret-id")[:12]
            result_value = make_evaluator_result(output_root, evaluation_ref=expected_ref)
            output = io.StringIO()
            with patch.object(cycle.evaluator, "evaluate_session", return_value=result_value), patch.object(cycle.selector, "_record_success_and_finish_attempt", side_effect=sqlite3.OperationalError("PRIVATE_DB_DETAIL")), redirect_stdout(output):
                status = cycle.run_cycle(db_path=db, state_path=state, output_root=output_root, now_epoch=now)
            self.assertEqual(status, 1)
            self.assertIn('"status": "STATE_WRITE_FAILED"', output.getvalue())
            self.assertNotIn("PRIVATE_DB_DETAIL", output.getvalue())
            with sqlite3.connect(state) as conn:
                row = conn.execute("SELECT status, error_phase, error_code FROM attempts").fetchone()
            self.assertEqual(row, ("failed", "attempt_ledger", "success_record_failed"))
            self.assertEqual(cycle.selector.load_processed_refs(state), set())

    def test_failure_notice_allowlists_phase_and_code_and_omits_untrusted_text(self):
        text = cycle.format_failure_notice({
            "status": "EVALUATION_FAILED",
            "error_phase": "provider_response",
            "error_code": "provider_nonzero_exit",
            "daily_cap_consumed": True,
            "exception": "private conversation detail",
        })
        self.assertIn("phase=provider_response", text)
        self.assertIn("code=provider_nonzero_exit", text)
        self.assertIn("日次試行枠は消費済み", text)
        self.assertNotIn("private conversation detail", text)

        forged = cycle.format_failure_notice({
            "status": "EVALUATION_FAILED",
            "error_phase": "private transcript text",
            "error_code": "api_key=secret-value",
            "daily_cap_consumed": True,
        })
        self.assertIn("phase=unknown", forged)
        self.assertIn("code=unknown_failure", forged)
        self.assertNotIn("secret-value", forged)

    def test_delivery_failure_notice_does_not_claim_evaluation_retry(self):
        text = cycle.delivery_failure_notice()
        self.assertIn("phase=delivery", text)
        self.assertIn("再評価は行っていません", text)


if __name__ == "__main__":
    unittest.main()
