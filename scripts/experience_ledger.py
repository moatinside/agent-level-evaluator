#!/usr/bin/env python3
"""Metadata-first experience ledger with approval-gated retrieval."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

_EXPERIENCE_ID = re.compile(r"^experience:[a-zA-Z0-9._-]+$")
_TASK_REF = re.compile(r"^task:[a-zA-Z0-9._-]+$")
_CONFIG_ID = re.compile(r"^config:[a-zA-Z0-9._-]+$")
_LESSON_REF = re.compile(r"^lesson:sha256:[a-f0-9]{64}$")
_OUTCOMES = {"passed", "blocked", "inconclusive", "failed"}
_FAILURES = {"none", "validation", "execution", "timeout", "malformed", "dependency", "unknown"}
_APPROVALS = {"pending", "approved", "rejected", "obsolete"}
_SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password)=\S+")
_URL_CRED_RE = re.compile(r"(?i)https?://[^\s/@:]+:[^\s/@]+@")
_LOCAL_PATH_RE = re.compile(r"(?:/Users/[^\s]+|/home/[^\s]+|[A-Za-z]:\\[^\s]+)")


def _redacted_summary(value: str) -> str:
    value = _URL_CRED_RE.sub("https://[REDACTED]@", value)
    value = _SECRET_RE.sub(lambda match: match.group(1) + "=[REDACTED]", value)
    value = _LOCAL_PATH_RE.sub("[LOCAL_PATH]", value)
    return value[:280]

def _result(status: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason, **extra}


def lesson_ref(lesson: str) -> str:
    return "lesson:sha256:" + hashlib.sha256(lesson.encode("utf-8")).hexdigest()


def build_record(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a record without retaining the raw lesson or execution text."""
    outcome = payload.get("outcome")
    failure = payload.get("failure_class", "none")
    lesson = payload.get("lesson")
    if not isinstance(lesson, str) or not lesson:
        raise ValueError("lesson must be a non-empty string")
    if outcome not in _OUTCOMES or failure not in _FAILURES:
        raise ValueError("invalid outcome or failure_class")
    if outcome == "passed" and failure != "none":
        raise ValueError("passed outcome must use failure_class=none")
    if outcome != "passed" and failure == "none":
        raise ValueError("non-passed outcome requires a failure_class")
    record = {
        "schema_version": 1,
        "experience_id": payload["experience_id"],
        "task_ref": payload["task_ref"],
        "configuration_id": payload["configuration_id"],
        "outcome": outcome,
        "failure_class": failure,
        "evidence_refs": list(payload.get("evidence_refs", [])),
        "lesson_ref": lesson_ref(lesson),
        "lesson_summary": _redacted_summary(lesson),
        "approval": "pending",
        "approval_actor_ref": None,
        "approval_reason_ref": None,
        "approved_at": None,
        "source": payload.get("source", "deterministic"),
        "created_at": payload.get("created_at", "unknown"),
    }
    return record


def validate_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return _result("inconclusive", "record must be an object")
    required = {"schema_version", "experience_id", "task_ref", "configuration_id", "outcome", "failure_class", "evidence_refs", "lesson_ref", "lesson_summary", "approval", "approval_actor_ref", "approval_reason_ref", "approved_at", "source", "created_at"}
    if set(record) != required:
        return _result("inconclusive", "record fields do not match schema")
    if record["schema_version"] != 1 or not _EXPERIENCE_ID.fullmatch(record["experience_id"]):
        return _result("inconclusive", "invalid schema version or experience_id")
    if not _TASK_REF.fullmatch(record["task_ref"]) or not _CONFIG_ID.fullmatch(record["configuration_id"]):
        return _result("inconclusive", "invalid task_ref or configuration_id")
    if record["outcome"] not in _OUTCOMES or record["failure_class"] not in _FAILURES or record["approval"] not in _APPROVALS:
        return _result("inconclusive", "invalid outcome, failure class, or approval")
    if not isinstance(record["lesson_summary"], str) or not record["lesson_summary"] or len(record["lesson_summary"]) > 280:
        return _result("inconclusive", "invalid lesson_summary")
    approval_fields = (record["approval_actor_ref"], record["approval_reason_ref"], record["approved_at"])
    if record["approval"] == "approved" and not all(isinstance(value, str) and value for value in approval_fields):
        return _result("inconclusive", "approved record lacks approval evidence")
    if record["approval"] != "approved" and any(value is not None for value in approval_fields):
        return _result("inconclusive", "non-approved record has approval evidence")
    if record["outcome"] == "passed" and record["failure_class"] != "none":
        return _result("inconclusive", "passed record has a failure class")
    if record["outcome"] != "passed" and record["failure_class"] == "none":
        return _result("inconclusive", "non-passed record lacks a failure class")
    if not isinstance(record["evidence_refs"], list) or not all(isinstance(x, str) and x for x in record["evidence_refs"]):
        return _result("inconclusive", "invalid evidence_refs")
    if not _LESSON_REF.fullmatch(record["lesson_ref"]) or record["source"] not in {"deterministic", "human_review"}:
        return _result("inconclusive", "invalid lesson_ref or source")
    return _result("valid", "record is valid")


def append_record(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    verdict = validate_record(record)
    if verdict["status"] != "valid":
        raise ValueError(verdict["reason"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    if json.loads(line).get("experience_id") == record["experience_id"]:
                        raise ValueError("duplicate experience_id")
                except json.JSONDecodeError:
                    continue
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def approve_record(path: Path, experience_id: str, actor_ref: str, reason_ref: str, approved_at: str) -> dict[str, Any]:
    if not all(isinstance(value, str) and value for value in (experience_id, actor_ref, reason_ref, approved_at)):
        raise ValueError("approval fields must be non-empty")
    if not path.exists():
        raise ValueError("ledger does not exist")
    lines = path.read_text(encoding="utf-8").splitlines()
    updated: dict[str, Any] | None = None
    output: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("experience_id") == experience_id:
            if record.get("approval") != "pending":
                raise ValueError("only pending records can be approved")
            record = {**record, "approval": "approved", "approval_actor_ref": actor_ref, "approval_reason_ref": reason_ref, "approved_at": approved_at}
            updated = record
        output.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
    if updated is None:
        raise ValueError("experience_id not found")
    if validate_record(updated)["status"] != "valid":
        raise ValueError("approval transition produced an invalid record")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return updated


def retrieve(path: Path, task_ref: str, configuration_id: str) -> list[dict[str, Any]]:
    """Return only valid, approved records for the same task/configuration."""
    if not path.exists():
        return []
    matches: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if validate_record(record)["status"] == "valid" and record["approval"] == "approved" and record["task_ref"] == task_ref and record["configuration_id"] == configuration_id:
            matches.append(record)
    return matches


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--retrieve-task")
    parser.add_argument("--retrieve-config")
    args = parser.parse_args()
    if args.retrieve_task and args.retrieve_config:
        print(json.dumps(retrieve(args.ledger, args.retrieve_task, args.retrieve_config), ensure_ascii=False, sort_keys=True))
        return 0
    if not args.input:
        parser.error("--input or both retrieval options are required")
    try:
        record = build_record(json.loads(args.input.read_text(encoding="utf-8")))
        append_record(args.ledger, record)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(json.dumps(_result("inconclusive", str(exc)), ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
