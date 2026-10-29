#!/usr/bin/env python3
"""Evaluate at most one recent, allowlisted Hermes conversation per JST day.

The session database is read-only. Only the exact allowlisted Discord channel is
eligible; session IDs are hashed before they enter the local dedupe ledger or
report filename. Conversation text is sent to Claude Code only after the user
has enabled this scheduled route.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evaluate_session_with_claude as evaluator  # noqa: E402

DB_PATH = Path.home() / ".hermes" / "state.db"
STATE_DIR = Path.home() / ".hermes" / "agent-level-evaluator-automation"
STATE_DB = STATE_DIR / "state.sqlite3"
REPORTS_DIR = ROOT / "evaluation-reports" / "automatic"
ALLOWLIST = ("AIBusinessDevelopment / #mobile（フランチャイズ）",)
ALLOWED_CHANNEL_IDS = {"1535083428083409008": ALLOWLIST[0]}
PROFILE_NAME = "default"
TIMEZONE = ZoneInfo("Asia/Tokyo")
LOOKBACK_HOURS = 28
MAX_MESSAGES = 120
MAX_PROMPT_CHARS = 20_000
MAX_PER_JST_DAY = 1


@dataclass(frozen=True)
class Candidate:
    # Keep the raw ID process-local. Never serialize or log this dataclass.
    session_id: str
    session_ref: str
    display_name: str
    ended_at: float
    message_count: int
    prompt_chars: int


def session_ref(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


def _readonly_uri(path: Path) -> str:
    return path.expanduser().resolve().as_uri() + "?mode=ro"


def load_processed_refs(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    with sqlite3.connect(_readonly_uri(state_path), uri=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evaluations'"
        ).fetchone()
        if not exists:
            return set()
        return {row[0] for row in conn.execute("SELECT session_ref FROM evaluations")}


def _jst_day_key(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, TIMEZONE).date().isoformat()


def attempts_today(state_path: Path, now_epoch: float) -> int:
    if not state_path.exists():
        return 0
    with sqlite3.connect(_readonly_uri(state_path), uri=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='attempts'"
        ).fetchone()
        if not exists:
            return 0
        return int(conn.execute(
            "SELECT count(*) FROM attempts WHERE jst_day = ?",
            (_jst_day_key(now_epoch),),
        ).fetchone()[0])


def select_candidate(
    db_path: Path,
    processed_refs: set[str],
    now_epoch: float,
    *,
    allowlist: tuple[str, ...] = ALLOWLIST,
    lookback_hours: int = LOOKBACK_HOURS,
    max_messages: int = MAX_MESSAGES,
    max_prompt_chars: int = MAX_PROMPT_CHARS,
) -> Candidate | None:
    """Choose the newest short, completed session matching the exact allowlist."""
    if not allowlist:
        return None
    channel_pairs = [(channel_id, name) for channel_id, name in ALLOWED_CHANNEL_IDS.items() if name in allowlist]
    if not channel_pairs:
        return None
    channel_filter = " OR ".join("(chat_id = ? AND display_name = ?)" for _ in channel_pairs)
    sql = f"""SELECT id, ended_at, display_name
              FROM sessions
              WHERE ended_at IS NOT NULL
                AND ended_at >= ? AND ended_at <= ?
                AND source = 'discord'
                AND chat_type = 'group'
                AND ({channel_filter})
                AND profile_name = ?
                AND COALESCE(hidden, 0) = 0
                AND COALESCE(archived, 0) = 0
              ORDER BY ended_at DESC, id DESC"""
    cutoff = now_epoch - lookback_hours * 3600
    params: list[Any] = [cutoff, now_epoch]
    for channel_id, name in channel_pairs:
        params.extend([channel_id, name])
    params.append(PROFILE_NAME)
    with sqlite3.connect(_readonly_uri(db_path), uri=True) as conn:
        rows = conn.execute(sql, params).fetchall()

    for raw_id, ended_at, display_name in rows:
        sid = str(raw_id)
        reference = session_ref(sid)
        if reference in processed_refs:
            continue
        try:
            messages = evaluator.read_session(db_path, sid)
        except (OSError, sqlite3.Error, ValueError):
            continue
        if not messages or len(messages) > max_messages:
            continue
        transcript, _ = evaluator.render_transcript(messages)
        prompt = evaluator.build_prompt(evaluator.DEFAULT_RUBRIC.read_text(encoding="utf-8"), transcript)
        if len(prompt) > max_prompt_chars:
            continue
        return Candidate(
            session_id=sid,
            session_ref=reference,
            display_name=str(display_name),
            ended_at=float(ended_at),
            message_count=len(messages),
            prompt_chars=len(prompt),
        )
    return None


def ensure_state_schema(state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(state_path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS evaluations (
            session_ref TEXT PRIMARY KEY,
            evaluated_at REAL NOT NULL,
            report_name TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS attempts (
            jst_day TEXT PRIMARY KEY,
            attempted_at REAL NOT NULL,
            session_ref TEXT NOT NULL,
            status TEXT NOT NULL,
            report_name TEXT,
            error_phase TEXT,
            error_code TEXT
        )""")
        attempt_columns = {row[1] for row in conn.execute("PRAGMA table_info(attempts)")}
        if "error_phase" not in attempt_columns:
            conn.execute("ALTER TABLE attempts ADD COLUMN error_phase TEXT")
        if "error_code" not in attempt_columns:
            conn.execute("ALTER TABLE attempts ADD COLUMN error_code TEXT")
        conn.commit()
    try:
        state_path.chmod(0o600)
    except OSError:
        pass


def _valid_existing_report(path: Path, session_id: str, reference: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if session_id in text or "http://" in text or "https://" in text:
        return False
    if f"`{reference[:12]}`" not in text:
        return False
    return all(f"### {axis}: " in text for axis in evaluator.AXES)


def _write_report_atomic(path: Path, report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".evaluation-", suffix=".tmp", delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(report)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name is not None:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass


def _record_success_and_finish_attempt(
    state_path: Path, candidate: Candidate, now_epoch: float, report_name: str
) -> None:
    with sqlite3.connect(state_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO evaluations(session_ref, evaluated_at, report_name) VALUES (?, ?, ?)",
            (candidate.session_ref, now_epoch, report_name),
        )
        cursor = conn.execute(
            "UPDATE attempts SET status = 'succeeded', report_name = ?, error_phase = NULL, error_code = NULL "
            "WHERE jst_day = ? AND session_ref = ? AND status = 'running'",
            (report_name, _jst_day_key(now_epoch), candidate.session_ref),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("reserved attempt was not found")


def _reserve_attempt(state_path: Path, candidate: Candidate, now_epoch: float) -> bool:
    with sqlite3.connect(state_path) as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO attempts(jst_day, attempted_at, session_ref, status) VALUES (?, ?, ?, 'running')",
            (_jst_day_key(now_epoch), now_epoch, candidate.session_ref),
        )
        conn.commit()
        return cursor.rowcount == 1


def _finish_attempt(
    state_path: Path,
    now_epoch: float,
    status: str,
    report_name: str | None = None,
    *,
    error_phase: str | None = None,
    error_code: str | None = None,
) -> None:
    with sqlite3.connect(state_path) as conn:
        conn.execute(
            "UPDATE attempts SET status = ?, report_name = ?, error_phase = ?, error_code = ? WHERE jst_day = ?",
            (status, report_name, error_phase, error_code, _jst_day_key(now_epoch)),
        )
        conn.commit()


def evaluate_candidate(
    candidate: Candidate,
    *,
    db_path: Path,
    state_path: Path,
    reports_dir: Path,
    now_epoch: float,
    claude_path: str | None = None,
) -> dict[str, Any]:
    """Run the existing evaluator and persist a minimal, read-back-checked report."""
    messages = evaluator.read_session(db_path, candidate.session_id)
    transcript, excerpts = evaluator.render_transcript(messages)
    rubric = evaluator.DEFAULT_RUBRIC.read_text(encoding="utf-8")
    prompt = evaluator.build_prompt(rubric, transcript)
    if len(messages) > MAX_MESSAGES or len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError("candidate exceeded automatic size limits after selection")

    output = reports_dir / f"{datetime.fromtimestamp(now_epoch, TIMEZONE):%Y-%m-%d}-{candidate.session_ref}-claude-evaluation.md"
    if output.exists():
        if _valid_existing_report(output, candidate.session_id, candidate.session_ref):
            return {"status": "RECOVERED_EXISTING_REPORT", "report": str(output), "messages": len(messages)}
        raise FileExistsError("a report already exists at the automatic output path")

    raw = evaluator.run_claude(prompt, claude_path or shutil.which("claude") or str(Path.home() / ".local/bin/claude"))
    axes = evaluator.validate_result(raw, len(messages))
    report = evaluator.make_report(candidate.session_id, axes, excerpts)
    _write_report_atomic(output, report)
    if output.read_text(encoding="utf-8") != report:
        raise OSError("report read-back did not match the written report")
    if not _valid_existing_report(output, candidate.session_id, candidate.session_ref):
        raise ValueError("report failed privacy/completeness read-back checks")
    return {"status": "OK", "report": str(output), "messages": len(messages), "axes": len(axes)}


def _emit(value: dict[str, Any], *, stream: Any = None) -> None:
    print(json.dumps(value, ensure_ascii=False), file=stream or sys.stdout)


def run_cycle(
    *,
    db_path: Path = DB_PATH,
    state_path: Path = STATE_DB,
    reports_dir: Path = REPORTS_DIR,
    now_epoch: float | None = None,
    dry_run: bool = False,
    claude_path: str | None = None,
) -> int:
    now = time.time() if now_epoch is None else now_epoch
    if dry_run:
        try:
            candidate = select_candidate(db_path, load_processed_refs(state_path), now)
        except (OSError, sqlite3.Error, ValueError):
            _emit({"status": "FAIL", "phase": "candidate_scan"})
            return 1
        if candidate is None:
            _emit({"status": "NO_CANDIDATE", "lookback_hours": LOOKBACK_HOURS})
        else:
            _emit({
                "status": "DRY_RUN",
                "channel": candidate.display_name,
                "messages": candidate.message_count,
                "prompt_chars": candidate.prompt_chars,
            })
        return 0

    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_suffix(".lock")
    with lock_path.open("a") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        ensure_state_schema(state_path)
        if attempts_today(state_path, now) >= MAX_PER_JST_DAY:
            return 0
        try:
            candidate = select_candidate(db_path, load_processed_refs(state_path), now)
        except (OSError, sqlite3.Error, ValueError):
            _emit({"status": "FAIL", "phase": "candidate_scan"})
            return 1
        if candidate is None:
            return 0
        if not _reserve_attempt(state_path, candidate, now):
            return 0
        try:
            result = evaluate_candidate(
                candidate,
                db_path=db_path,
                state_path=state_path,
                reports_dir=reports_dir,
                now_epoch=now,
                claude_path=claude_path,
            )
            _record_success_and_finish_attempt(state_path, candidate, now, Path(result["report"]).name)
        except (OSError, sqlite3.Error, ValueError, RuntimeError, TimeoutError, subprocess.TimeoutExpired):
            _finish_attempt(state_path, now, "failed")
            _emit({"status": "FAIL", "phase": "external_evaluation_or_report"})
            return 1
        result["channel"] = candidate.display_name
        _emit(result)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Automatically evaluate one recent allowlisted Hermes session per JST day.")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--state-db", type=Path, default=STATE_DB)
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--claude-path")
    args = parser.parse_args()
    return run_cycle(
        db_path=args.db.expanduser(),
        state_path=args.state_db.expanduser(),
        reports_dir=args.reports_dir.expanduser(),
        dry_run=args.dry_run,
        claude_path=args.claude_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
