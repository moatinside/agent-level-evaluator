#!/usr/bin/env python3
"""Fail-closed deterministic validator for task completion evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CONDITION_TYPES = {"command_exit_zero", "tests_pass", "artifact_present"}


def validate(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"status": "inconclusive", "complete": False, "reason": "payload must be an object"}
    if payload.get("schema_version") != 1:
        return {"status": "inconclusive", "complete": False, "reason": "schema_version must be 1"}
    task_id = payload.get("task_id")
    conditions = payload.get("conditions")
    evidence = payload.get("evidence")
    if not isinstance(task_id, str) or not task_id:
        return {"status": "inconclusive", "complete": False, "reason": "task_id must be non-empty"}
    if not isinstance(conditions, list) or not conditions:
        return {"status": "inconclusive", "complete": False, "reason": "conditions must be non-empty"}
    if not isinstance(evidence, list):
        return {"status": "inconclusive", "complete": False, "reason": "evidence must be an array"}

    required: dict[str, str] = {}
    for condition in conditions:
        if not isinstance(condition, dict):
            return {"status": "inconclusive", "complete": False, "reason": "condition must be an object"}
        cid, ctype = condition.get("condition_id"), condition.get("type")
        if not isinstance(cid, str) or not cid or ctype not in CONDITION_TYPES:
            return {"status": "inconclusive", "complete": False, "reason": "invalid condition"}
        if condition.get("required") is True:
            required[cid] = ctype

    by_id: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if not isinstance(item, dict):
            return {"status": "inconclusive", "complete": False, "reason": "evidence item must be an object"}
        cid = item.get("condition_id")
        if not isinstance(cid, str) or cid in by_id or item.get("verifier") != "deterministic":
            return {"status": "inconclusive", "complete": False, "reason": "invalid or duplicate evidence"}
        if item.get("status") not in {"verified", "failed"}:
            return {"status": "inconclusive", "complete": False, "reason": "invalid evidence status"}
        by_id[cid] = item

    missing = sorted(cid for cid in required if cid not in by_id)
    if missing:
        return {"status": "inconclusive", "complete": False, "reason": "required evidence missing", "missing": missing}
    failed = sorted(cid for cid in required if by_id[cid]["status"] == "failed")
    if failed:
        return {"status": "blocked", "complete": False, "reason": "required condition failed", "failed": failed}

    for cid, ctype in required.items():
        item = by_id[cid]
        if ctype == "command_exit_zero" and item.get("exit_code") != 0:
            return {"status": "blocked", "complete": False, "reason": "command exit code was not zero", "failed": [cid]}
        if ctype == "tests_pass" and (item.get("fail_count") != 0 or not isinstance(item.get("pass_count"), int)):
            return {"status": "blocked", "complete": False, "reason": "test evidence is not clean", "failed": [cid]}
        if ctype == "artifact_present" and not isinstance(item.get("artifact_ref"), str):
            return {"status": "inconclusive", "complete": False, "reason": "artifact reference missing", "missing": [cid]}
    return {"status": "passed", "complete": True, "task_id": task_id, "verified_conditions": sorted(required)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(json.loads(args.input.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        result = {"status": "inconclusive", "complete": False, "reason": f"invalid input: {exc}"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
