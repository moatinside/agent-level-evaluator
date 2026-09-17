#!/usr/bin/env python3
"""Hermes通常実行を観測する、Production非接続のShadow adapter.

入力は完了済みAgentイベントを受け取り、既存の決定的Validatorと
metadata-first Evidence Collectorへ渡す。回答の外部送信・置換・自動昇格は行わない。
final_textは検証中だけメモリ上で扱い、Evidenceへ保存しない。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_shadow_policy import evaluate, write_evidence  # noqa: E402


class AdapterError(ValueError):
    """入力イベントがRuntime Shadow契約に違反した。"""


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AdapterError(f"{name} must be a non-empty string")
    return value


def validate_runtime_event(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise AdapterError("event must be an object")
    if event.get("schema_version") != 1:
        raise AdapterError("schema_version must be 1")
    if event.get("event_type") != "completed_response":
        raise AdapterError("event_type must be completed_response")
    require_string(event.get("request_id"), "request_id")
    require_string(event.get("final_text"), "final_text")
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        raise AdapterError("metadata must be an object")
    if metadata.get("trigger_origin") != "hermes":
        raise AdapterError("metadata.trigger_origin must be hermes")
    if metadata.get("execution_mode") not in (None, "shadow"):
        raise AdapterError("metadata.execution_mode must be shadow")
    policy = event.get("policy")
    if not isinstance(policy, dict):
        raise AdapterError("policy must be an object")
    trace = event.get("trace", {})
    if not isinstance(trace, dict):
        raise AdapterError("trace must be an object")
    for key in ("tool_count", "step_count"):
        if key in trace and (not isinstance(trace[key], int) or trace[key] < 0):
            raise AdapterError(f"trace.{key} must be a non-negative integer")
    return event


def adapt(event: Any, evidence_output: Path) -> dict[str, Any]:
    event = validate_runtime_event(event)
    # live_shadow_policy owns hash validation, response validation, and collection.
    request = {
        "schema_version": 1,
        "request_id": event["request_id"],
        "final_text": event["final_text"],
        "metadata": {**event["metadata"], "execution_mode": "shadow"},
        "policy": event["policy"],
    }
    decision = evaluate(request)
    decision["adapter"] = "hermes_shadow"
    decision["delivery_attempted"] = False
    decision["side_effect_status"] = "not_attempted"
    decision["trace_metadata"] = {
        key: event["trace"][key]
        for key in ("tool_count", "step_count")
        if key in event["trace"]
    }
    decision["evidence_persisted"] = False
    decision["evidence_error_code"] = None
    try:
        write_evidence(request, decision, evidence_output)
    except (OSError, ValueError) as exc:
        decision["evidence_error_code"] = "evidence_write_failed"
        print(f"evidence persistence failed: {type(exc).__name__}", file=sys.stderr)
    else:
        decision["evidence_persisted"] = True
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes completed-response Shadow adapter")
    parser.add_argument("--evidence-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        event = json.load(sys.stdin)
        decision = adapt(event, args.evidence_output)
    except (json.JSONDecodeError, AdapterError, OSError, ValueError) as exc:
        decision = {
            "schema_version": 1,
            "adapter": "hermes_shadow",
            "status": "inconclusive",
            "allowed": False,
            "delivery_attempted": False,
            "side_effect_status": "not_attempted",
            "evidence_persisted": False,
            "evidence_error_code": "invalid_runtime_event",
            "reason": f"invalid runtime event: {type(exc).__name__}",
        }
        print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    if decision["status"] != "passed":
        return 1
    if not decision["evidence_persisted"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
