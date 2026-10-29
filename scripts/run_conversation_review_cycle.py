#!/usr/bin/env python3
"""Run one new-format review using the existing allowlist and shared daily cap.

This is a local one-shot implementation path, not a scheduler or Cron change.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sqlite3
import stat
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import auto_evaluate_recent_session as selector  # noqa: E402
import evaluate_session_with_claude as evaluator  # noqa: E402


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False))


def _safe_failure(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, evaluator.EvaluationFailure):
        return exc.phase, exc.code
    return "unknown", "unknown_failure"


def _daily_cap_consumed_after_reservation_error(state_path: Path, now: float) -> bool | None:
    try:
        return selector.attempts_today(state_path, now) >= selector.MAX_PER_JST_DAY
    except Exception:
        return None


def _result_matches_candidate(result: dict[str, Any], candidate: Any, output_root: Path) -> bool:
    expected_ref = candidate.session_ref[:12]
    if result.get("evaluation_ref") != expected_ref:
        return False
    try:
        root_info = output_root.lstat()
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            return False
        expected_dir = output_root.resolve(strict=True) / expected_ref
        evaluation_path = Path(result["evaluation"]).resolve(strict=True)
        report_path = Path(result["report"]).resolve(strict=True)
        if not (
            evaluation_path == expected_dir / "evaluation.json"
            and report_path == expected_dir / "report.md"
            and evaluation_path.is_file()
            and report_path.is_file()
        ):
            return False
        record = json.loads(evaluation_path.read_text(encoding="utf-8"))
        if not evaluator.validate_persisted_record(record) or record.get("evaluation_ref") != expected_ref:
            return False
        report = report_path.read_text(encoding="utf-8")
        return report == evaluator.make_review_report(record)
    except Exception:
        return False


def format_failure_notice(result: dict[str, Any]) -> str:
    phase = result.get("error_phase")
    code = result.get("error_code")
    if not isinstance(phase, str) or phase not in evaluator.SAFE_FAILURE_PHASES:
        phase = "unknown"
    if not isinstance(code, str) or code not in evaluator.SAFE_FAILURE_CODES:
        code = "unknown_failure"
    status = result.get("status")
    if not isinstance(status, str):
        status = "unknown"
    descriptions = {
        "EVALUATION_FAILED": "評価に失敗しました",
        "STATE_WRITE_FAILED": "評価後の状態記録に失敗しました。レポート配信は保留しています",
        "FAIL": "評価開始前の処理に失敗しました",
    }
    description = descriptions.get(status, "評価処理に失敗しました")
    cap_consumed = result.get("daily_cap_consumed")
    if cap_consumed is True:
        cap = "日次試行枠は消費済みです"
    elif cap_consumed is False:
        cap = "日次試行枠は未消費です"
    else:
        cap = "日次試行枠の消費状態は確認できません"
    return f"Agent Level v2: {description}（phase={phase}, code={code}）。{cap}。"


def delivery_failure_notice() -> str:
    return "Agent Level v2: 評価結果の読戻し／配信準備に失敗しました（phase=delivery, code=deliverable_unavailable）。Claudeの再評価は行っていません。"


def run_cycle(*, db_path: Path = selector.DB_PATH, state_path: Path = selector.STATE_DB, output_root: Path = evaluator.OUTPUT_ROOT, now_epoch: float | None = None, dry_run: bool = False, claude_path: str | None = None) -> int:
    now = time.time() if now_epoch is None else now_epoch
    if dry_run:
        try:
            candidate = selector.select_candidate(db_path, selector.load_processed_refs(state_path), now)
        except Exception:
            _emit({"status": "FAIL", "error_phase": "candidate_scan", "error_code": "candidate_scan_failed", "daily_cap_consumed": False})
            return 1
        if candidate is None:
            _emit({"status": "NO_CANDIDATE", "lookback_hours": selector.LOOKBACK_HOURS})
        else:
            _emit({"status": "DRY_RUN", "channel": candidate.display_name, "messages": candidate.message_count, "prompt_chars": candidate.prompt_chars})
        return 0

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        _emit({"status": "FAIL", "error_phase": "state_write", "error_code": "state_schema_failed", "daily_cap_consumed": None})
        return 1
    lock_path = state_path.with_suffix(".lock")
    try:
        lock_handle = lock_path.open("a")
    except OSError:
        _emit({"status": "FAIL", "error_phase": "lock", "error_code": "lock_unavailable", "daily_cap_consumed": None})
        return 1
    with lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _emit({"status": "LOCKED"})
            return 0
        except OSError:
            _emit({"status": "FAIL", "error_phase": "lock", "error_code": "lock_unavailable", "daily_cap_consumed": None})
            return 1
        try:
            selector.ensure_state_schema(state_path)
        except Exception:
            _emit({"status": "FAIL", "error_phase": "state_write", "error_code": "state_schema_failed", "daily_cap_consumed": None})
            return 1
        try:
            attempts = selector.attempts_today(state_path, now)
        except Exception:
            _emit({"status": "FAIL", "error_phase": "state_read", "error_code": "state_read_failed", "daily_cap_consumed": None})
            return 1
        if attempts >= selector.MAX_PER_JST_DAY:
            _emit({"status": "DAILY_CAP", "limit": selector.MAX_PER_JST_DAY})
            return 0
        try:
            candidate = selector.select_candidate(db_path, selector.load_processed_refs(state_path), now)
        except Exception:
            _emit({"status": "FAIL", "error_phase": "candidate_scan", "error_code": "candidate_scan_failed", "daily_cap_consumed": False})
            return 1
        if candidate is None:
            _emit({"status": "NO_CANDIDATE", "lookback_hours": selector.LOOKBACK_HOURS})
            return 0
        try:
            reserved = selector._reserve_attempt(state_path, candidate, now)
        except Exception:
            cap_consumed = _daily_cap_consumed_after_reservation_error(state_path, now)
            _emit({"status": "FAIL", "error_phase": "state_write", "error_code": "attempt_reservation_failed", "daily_cap_consumed": cap_consumed})
            return 1
        if not reserved:
            _emit({"status": "DAILY_CAP", "limit": selector.MAX_PER_JST_DAY})
            return 0
        try:
            result = evaluator.evaluate_session(candidate.session_id, db_path=db_path, output_root=output_root, claude_path=claude_path)
        except Exception as exc:
            error_phase, error_code = _safe_failure(exc)
            try:
                selector._finish_attempt(state_path, now, "failed", error_phase=error_phase, error_code=error_code)
            except Exception:
                error_phase, error_code = "attempt_ledger", "attempt_failure_record_failed"
            _emit({"status": "EVALUATION_FAILED", "error_phase": error_phase, "error_code": error_code, "daily_cap_consumed": True})
            return 1
        valid_result = (
            isinstance(result, dict)
            and result.get("status") == "OK"
            and all(key in result for key in ("evaluation_ref", "evaluation", "report", "axes", "changes"))
        )
        if valid_result:
            valid_result = _result_matches_candidate(result, candidate, output_root)
        if not valid_result:
            error_phase, error_code = "result_validation", "incomplete_evaluator_result"
            try:
                selector._finish_attempt(state_path, now, "failed", error_phase=error_phase, error_code=error_code)
            except Exception:
                error_phase, error_code = "attempt_ledger", "attempt_failure_record_failed"
            _emit({"status": "EVALUATION_FAILED", "error_phase": error_phase, "error_code": error_code, "daily_cap_consumed": True})
            return 1
        relative_report = f"{candidate.session_ref[:12]}/report.md"
        try:
            selector._record_success_and_finish_attempt(state_path, candidate, now, relative_report)
        except Exception:
            try:
                selector._finish_attempt(state_path, now, "failed", error_phase="attempt_ledger", error_code="success_record_failed")
            except Exception:
                pass
            _emit({"status": "STATE_WRITE_FAILED", "error_phase": "attempt_ledger", "error_code": "success_record_failed", "daily_cap_consumed": True})
            return 1
        _emit({"status": "OK", "evaluation_ref": result["evaluation_ref"], "report": result["report"], "axes": result["axes"], "changes": result["changes"]})
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Select and evaluate at most one approved recent conversation per JST day")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--claude-path", default=None)
    args = parser.parse_args()
    return run_cycle(dry_run=args.dry_run, claude_path=args.claude_path)


if __name__ == "__main__":
    raise SystemExit(main())
