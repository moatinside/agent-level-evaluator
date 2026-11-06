from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_conversation_review_cycle.py"
spec = importlib.util.spec_from_file_location("run_conversation_review_cycle", SCRIPT)
assert spec and spec.loader
cycle = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cycle
spec.loader.exec_module(cycle)

SYNTHETIC_CHANNEL_ID = "000000000000000000"
SYNTHETIC_CHANNEL_NAME = "Synthetic Evaluation Channel"
NOW = 2_000_000_000.0


def write_policy(path: Path, enabled: bool = False) -> Path:
    path.write_text(json.dumps({
        "external_evaluation_enabled": enabled,
        "provider": "claude-code",
        "approved_payload": "user_assistant_message_content",
        "allowed_channels": [{
            "channel_id": SYNTHETIC_CHANNEL_ID,
            "display_name": SYNTHETIC_CHANNEL_NAME,
        }],
    }), encoding="utf-8")
    return path


def make_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE sessions (
            id TEXT, ended_at REAL, source TEXT, chat_type TEXT,
            display_name TEXT, profile_name TEXT, hidden INTEGER, archived INTEGER, chat_id TEXT
        )""")
        conn.execute("""CREATE TABLE messages (
            id INTEGER, session_id TEXT, role TEXT, content TEXT,
            timestamp REAL, active INTEGER
        )""")
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, 'discord', 'group', ?, 'default', 0, 0, ?)",
            ("synthetic-session", NOW - 10, SYNTHETIC_CHANNEL_NAME, SYNTHETIC_CHANNEL_ID),
        )
        conn.executemany(
            "INSERT INTO messages VALUES (?, 'synthetic-session', ?, ?, ?, 1)",
            [(1, "user", "synthetic question", NOW - 9), (2, "assistant", "synthetic answer", NOW - 8)],
        )


class ConversationReviewCyclePolicyTests(unittest.TestCase):
    def test_missing_policy_blocks_before_state_or_provider_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.StringIO()
            with patch.object(cycle.evaluator, "evaluate_session") as evaluate, redirect_stdout(output):
                status = cycle.run_cycle(
                    db_path=root / "missing.db", state_path=root / "state.sqlite3",
                    output_root=root / "reports", now_epoch=NOW,
                    policy_path=root / "missing-policy.json",
                )
            self.assertEqual(status, 2)
            evaluate.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["error_code"], "policy_not_configured")
            self.assertFalse((root / "state.sqlite3").exists())
            self.assertFalse((root / "reports").exists())

    def test_disabled_policy_blocks_live_send_before_database_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = write_policy(root / "policy.json", enabled=False)
            output = io.StringIO()
            with patch.object(cycle.evaluator, "evaluate_session") as evaluate, redirect_stdout(output):
                status = cycle.run_cycle(
                    db_path=root / "missing.db", state_path=root / "state.sqlite3",
                    output_root=root / "reports", now_epoch=NOW, policy_path=policy,
                )
            self.assertEqual(status, 2)
            evaluate.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["error_code"], "external_evaluation_disabled")
            self.assertFalse((root / "state.sqlite3").exists())

    def test_dry_run_with_disabled_policy_selects_synthetic_candidate_without_channel_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "state.db"
            make_db(db)
            policy = write_policy(root / "policy.json", enabled=False)
            output = io.StringIO()
            with patch.object(cycle.evaluator, "evaluate_session") as evaluate, redirect_stdout(output):
                status = cycle.run_cycle(
                    db_path=db, state_path=root / "state.sqlite3", output_root=root / "reports",
                    now_epoch=NOW, dry_run=True, policy_path=policy,
                )
            self.assertEqual(status, 0)
            evaluate.assert_not_called()
            notice = json.loads(output.getvalue())
            self.assertEqual(notice["status"], "DRY_RUN")
            self.assertNotIn(SYNTHETIC_CHANNEL_NAME, output.getvalue())
            self.assertNotIn(SYNTHETIC_CHANNEL_ID, output.getvalue())

    def test_output_under_repository_is_blocked_before_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = write_policy(root / "policy.json", enabled=True)
            output = io.StringIO()
            with patch.object(cycle.evaluator, "evaluate_session") as evaluate, redirect_stdout(output):
                status = cycle.run_cycle(
                    db_path=root / "missing.db", state_path=root / "state.sqlite3",
                    output_root=ROOT / "conversation-review-output", now_epoch=NOW,
                    policy_path=policy,
                )
            self.assertEqual(status, 2)
            evaluate.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["error_code"], "repository_output_path")
            self.assertFalse((root / "state.sqlite3").exists())

    def test_unknown_cli_argument_is_not_echoed(self) -> None:
        canary = "SYNTHETIC-ARGUMENT-CANARY"
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_conversation_review_cycle.py"), "--unknown", canary],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(canary, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "invalid command line arguments\n")


if __name__ == "__main__":
    unittest.main()
