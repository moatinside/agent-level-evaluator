from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "auto_evaluate_recent_session.py"
spec = importlib.util.spec_from_file_location("auto_evaluate_recent_session", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

ALLOWLIST_CHANNEL = module.ALLOWLIST[0]
ALLOWLIST_CHANNEL_ID = next(iter(module.ALLOWED_CHANNEL_IDS))


def make_db(path: Path, rows: list[tuple[str, float, str, str, str, int, int, list[str]]]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE sessions (
            id TEXT, ended_at REAL, source TEXT, chat_type TEXT,
            display_name TEXT, profile_name TEXT, hidden INTEGER, archived INTEGER, chat_id TEXT
        )""")
        conn.execute("""CREATE TABLE messages (
            id INTEGER, session_id TEXT, role TEXT, content TEXT,
            timestamp REAL, active INTEGER
        )""")
        mid = 0
        for sid, ended, source, chat_type, name, hidden, archived, contents in rows:
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, 'default', ?, ?, ?)",
                (sid, ended, source, chat_type, name, hidden, archived, ALLOWLIST_CHANNEL_ID if name == ALLOWLIST_CHANNEL else "wrong-channel-id"),
            )
            for index, content in enumerate(contents):
                mid += 1
                role = "user" if index % 2 == 0 else "assistant"
                conn.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, 1)",
                    (mid, sid, role, content, ended - len(contents) + index),
                )


class AutoEvaluateRecentSessionTests(unittest.TestCase):
    def test_state_schema_migrates_existing_attempts_without_changing_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.sqlite3"
            now = 2_000_000_000.0
            day = module._jst_day_key(now)
            with sqlite3.connect(state) as conn:
                conn.execute("CREATE TABLE attempts (jst_day TEXT PRIMARY KEY, attempted_at REAL NOT NULL, session_ref TEXT NOT NULL, status TEXT NOT NULL, report_name TEXT)")
                conn.execute("INSERT INTO attempts VALUES (?, ?, ?, ?, ?)", (day, now, "hashed-ref", "failed", None))

            module.ensure_state_schema(state)
            with sqlite3.connect(state) as conn:
                before = conn.execute("SELECT jst_day, attempted_at, session_ref, status, report_name, error_phase, error_code FROM attempts").fetchone()
            self.assertEqual(before, (day, now, "hashed-ref", "failed", None, None, None))

            module._finish_attempt(state, now, "failed", error_phase="provider_response", error_code="provider_timeout")
            with sqlite3.connect(state) as conn:
                after = conn.execute("SELECT status, error_phase, error_code FROM attempts WHERE jst_day = ?", (day,)).fetchone()
            self.assertEqual(after, ("failed", "provider_response", "provider_timeout"))

    def test_selects_newest_exact_allowlist_candidate_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            now = 2_000_000_000.0
            make_db(db, [
                ("allowed-old", now - 100, "discord", "group", ALLOWLIST_CHANNEL, 0, 0, ["q", "a"]),
                ("allowed-new", now - 10, "discord", "group", ALLOWLIST_CHANNEL, 0, 0, ["q2", "a2"]),
                ("other-channel", now, "discord", "group", "AIBusinessDevelopment / #scs", 0, 0, ["private", "text"]),
                ("dm", now, "discord", "dm", ALLOWLIST_CHANNEL, 0, 0, ["dm", "text"]),
            ])
            candidate = module.select_candidate(db, set(), now)
            self.assertIsNotNone(candidate)
            assert candidate
            self.assertEqual(candidate.session_id, "allowed-new")
            self.assertEqual(candidate.display_name, ALLOWLIST_CHANNEL)

    def test_requires_stable_channel_id_in_addition_to_display_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            now = 2_000_000_000.0
            make_db(db, [("wrong-channel-id", now - 10, "discord", "group", ALLOWLIST_CHANNEL, 0, 0, ["q", "a"])])
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE sessions SET chat_id = 'wrong-id'")
            self.assertIsNone(module.select_candidate(db, set(), now))

    def test_skips_oversized_session_and_selects_next_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            now = 2_000_000_000.0
            make_db(db, [
                ("small", now - 20, "discord", "group", ALLOWLIST_CHANNEL, 0, 0, ["q", "a"]),
                ("large", now - 10, "discord", "group", ALLOWLIST_CHANNEL, 0, 0, ["q", "a", "q2", "a2"]),
            ])
            candidate = module.select_candidate(db, set(), now, max_messages=3)
            self.assertIsNotNone(candidate)
            assert candidate
            self.assertEqual(candidate.session_id, "small")

    def test_daily_cap_and_dedupe_ledger_store_only_hashed_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.sqlite3"
            module.ensure_state_schema(state)
            candidate = module.Candidate("private-session-id", module.session_ref("private-session-id"), ALLOWLIST_CHANNEL, 2_000_000_000.0, 2, 100)
            self.assertTrue(module._reserve_attempt(state, candidate, 2_000_000_000.0))
            module._finish_attempt(state, 2_000_000_000.0, "failed")
            self.assertEqual(module.load_processed_refs(state), set())
            self.assertEqual(module.attempts_today(state, 2_000_000_000.0), 1)
            with sqlite3.connect(state) as conn:
                saved = conn.execute("SELECT session_ref, status, report_name FROM attempts").fetchone()
            self.assertEqual(saved, (candidate.session_ref, "failed", None))
            self.assertNotIn("private-session-id", str(saved))

    def test_evaluation_writes_valid_report_without_claiming_cycle_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            state = Path(tmp) / "automation" / "state.sqlite3"
            reports = Path(tmp) / "reports"
            now = 2_000_000_000.0
            sid = "session-private-id"
            make_db(db, [(sid, now - 10, "discord", "group", ALLOWLIST_CHANNEL, 0, 0, ["質問 https://example.test/x", "回答"])] )
            module.ensure_state_schema(state)
            candidate = module.select_candidate(db, set(), now)
            self.assertIsNotNone(candidate)
            assert candidate
            fake_result = {"axes": [
                {"axis": axis, "status": "partial", "evidence_positions": [1], "reason": "根拠に基づく短い理由。"}
                for axis in module.evaluator.AXES
            ]}
            with patch.object(module.evaluator, "run_claude", return_value=fake_result) as call:
                result = module.evaluate_candidate(
                    candidate, db_path=db, state_path=state, reports_dir=reports,
                    now_epoch=now, claude_path="/fake/claude",
                )
            self.assertEqual(call.call_count, 1)
            self.assertEqual(result["status"], "OK")
            report = Path(result["report"]).read_text(encoding="utf-8")
            self.assertNotIn(sid, report)
            self.assertNotIn("https://", report)
            self.assertIn(candidate.session_ref[:12], report)
            self.assertEqual(module.load_processed_refs(state), set())

    def test_success_and_attempt_terminal_state_commit_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "automation" / "state.sqlite3"
            now = 2_000_000_000.0
            module.ensure_state_schema(state)
            candidate = module.Candidate("private-session-id", module.session_ref("private-session-id"), ALLOWLIST_CHANNEL, now, 2, 100)
            self.assertTrue(module._reserve_attempt(state, candidate, now))

            with sqlite3.connect(state) as conn:
                conn.execute("""CREATE TRIGGER reject_success BEFORE UPDATE ON attempts
                    WHEN NEW.status = 'succeeded'
                    BEGIN SELECT RAISE(ABORT, 'synthetic transaction failure'); END""")

            with self.assertRaises(sqlite3.IntegrityError):
                module._record_success_and_finish_attempt(state, candidate, now, "report.md")

            with sqlite3.connect(state) as conn:
                attempt = conn.execute("SELECT status, report_name FROM attempts").fetchone()
                evaluation_count = conn.execute("SELECT count(*) FROM evaluations").fetchone()[0]
            self.assertEqual(attempt, ("running", None))
            self.assertEqual(evaluation_count, 0)

    def test_run_cycle_does_not_evaluate_twice_in_one_jst_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "state.db"
            state = root / "state.sqlite3"
            now = 2_000_000_000.0
            make_db(db, [("session1", now - 10, "discord", "group", ALLOWLIST_CHANNEL, 0, 0, ["q", "a"])] )
            module.ensure_state_schema(state)
            candidate = module.select_candidate(db, set(), now)
            assert candidate
            self.assertTrue(module._reserve_attempt(state, candidate, now))
            module._finish_attempt(state, now, "succeeded", "existing.md")
            output = io.StringIO()
            with patch.object(module.evaluator, "run_claude") as call, redirect_stdout(output):
                status = module.run_cycle(db_path=db, state_path=state, reports_dir=root / "reports", now_epoch=now)
            self.assertEqual(status, 0)
            call.assert_not_called()
            self.assertEqual(output.getvalue(), "")
    def test_run_cycle_evaluates_once_and_emits_sanitized_report_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "state.db"
            state = root / "state.sqlite3"
            reports = root / "reports"
            now = 2_000_000_000.0
            sid = "session-private-e2e"
            make_db(db, [(sid, now - 10, "discord", "group", ALLOWLIST_CHANNEL, 0, 0, ["q https://secret.example", "a"])])
            fake_result = {"axes": [
                {"axis": axis, "status": "partial", "evidence_positions": [1], "reason": "理由。"}
                for axis in module.evaluator.AXES
            ]}
            output = io.StringIO()
            with patch.object(module.evaluator, "run_claude", return_value=fake_result) as call, redirect_stdout(output):
                status = module.run_cycle(
                    db_path=db, state_path=state, reports_dir=reports,
                    now_epoch=now, claude_path="/fake/claude",
                )
            self.assertEqual(status, 0)
            self.assertEqual(call.call_count, 1)
            notice = json.loads(output.getvalue())
            self.assertEqual(notice["status"], "OK")
            self.assertEqual(notice["messages"], 2)
            self.assertNotIn(sid, output.getvalue())
            report = Path(notice["report"]).read_text(encoding="utf-8")
            self.assertNotIn(sid, report)
            self.assertNotIn("https://secret.example", report)
            with sqlite3.connect(state) as conn:
                attempt = conn.execute("SELECT status, report_name FROM attempts").fetchone()
            self.assertEqual(attempt, ("succeeded", Path(notice["report"]).name))

    def test_failed_attempt_still_consumes_the_daily_send_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "state.db"
            state = root / "state.sqlite3"
            now = 2_000_000_000.0
            make_db(db, [("session-failed", now - 10, "discord", "group", ALLOWLIST_CHANNEL, 0, 0, ["q", "a"])])
            module.ensure_state_schema(state)
            candidate = module.select_candidate(db, set(), now)
            assert candidate
            self.assertTrue(module._reserve_attempt(state, candidate, now))
            module._finish_attempt(state, now, "failed")
            output = io.StringIO()
            with patch.object(module.evaluator, "run_claude") as call, redirect_stdout(output):
                status = module.run_cycle(db_path=db, state_path=state, reports_dir=root / "reports", now_epoch=now)
            self.assertEqual(status, 0)
            call.assert_not_called()
            self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
