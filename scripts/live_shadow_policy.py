#!/usr/bin/env python3
"""Deterministic Hermes-compatible shadow/strict policy adapter.

The adapter evaluates one completed response and emits a decision. It never
sends a message. Raw response text is used transiently for validation and is
not persisted by the Evidence Collector.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_operational_evidence import append_record, collect, require_hash_id  # noqa: E402
from response_validation import validate_text  # noqa: E402

STATUSES = {"passed", "blocked", "inconclusive"}


def timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def validate_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    if request.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    require_string(request.get("request_id"), "request_id")
    require_string(request.get("final_text"), "final_text")
    metadata = request.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    for name in ("agent_configuration_id", "evaluator_configuration_id"):
        require_hash_id(metadata.get(name), f"metadata.{name}")
    policy = request.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("policy must be an object")
    for name in ("required_patterns", "forbidden_patterns"):
        value = policy.get(name, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"policy.{name} must be an array of strings")
    return request


def evaluate(request: dict[str, Any]) -> dict[str, Any]:
    request = validate_request(request)
    result = validate_text(
        request["final_text"],
        required_patterns=request["policy"].get("required_patterns", []),
        forbidden_patterns=request["policy"].get("forbidden_patterns", []),
    )
    status = result["status"]
    if status not in STATUSES:
        status = "inconclusive"
    passed = status == "passed"
    return {
        "schema_version": 1,
        "request_id": request["request_id"],
        "status": status,
        "allowed": passed,
        "final_text": request["final_text"] if passed else None,
        "evidence_ref": f"run:{request['request_id']}",
        "reason": None if passed else "; ".join(issue["message"] for issue in result["issues"]) or "validator could not determine a safe result",
        "attempt_count": 1,
        "correction_count": 0,
        "issues": result["issues"],
    }


def write_evidence(request: dict[str, Any], decision: dict[str, Any], output: Path) -> None:
    started = timestamp()
    metadata = request["metadata"]
    run_result = {
        "status": decision["status"],
        "delivery_allowed": decision["allowed"],
        "attempts": [{"iteration": 1, "validation": {"status": decision["status"], "issues": decision["issues"]}}],
        "reason": decision["reason"],
    }
    record = collect(
        request,
        run_result,
        {
            "run_id": request["request_id"],
            "level": 5,
            "capability_id": "self_reflection",
            "capability_contract_version": "1.0.0",
            "agent_configuration_id": metadata["agent_configuration_id"],
            "evaluator_configuration_id": metadata["evaluator_configuration_id"],
            "scenario_id": request["request_id"],
            "trigger_origin": "harness",
            "environment_class": "shadow",
            "execution_mode": "shadow",
            "decision": decision["status"],
            "side_effect_status": "not_attempted",
            "started_at": started,
            "ended_at": timestamp(),
        },
    )
    append_record(output, record)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-output", type=Path)
    args = parser.parse_args()
    request: Any = None
    try:
        request = json.load(sys.stdin)
        decision = evaluate(request)
    except (json.JSONDecodeError, ValueError) as exc:
        decision = {
            "schema_version": 1,
            "request_id": request.get("request_id") if isinstance(request, dict) else None,
            "status": "inconclusive",
            "allowed": False,
            "final_text": None,
            "evidence_ref": None,
            "reason": f"invalid request: {exc}",
            "attempt_count": 0,
            "correction_count": 0,
            "issues": [],
        }
    else:
        decision["evidence_persisted"] = None
        decision["evidence_error_code"] = None
        if args.evidence_output is not None:
            try:
                write_evidence(request, decision, args.evidence_output)
            except (OSError, ValueError) as exc:
                decision["evidence_persisted"] = False
                decision["evidence_error_code"] = "evidence_write_failed"
                print(f"evidence persistence failed: {type(exc).__name__}", file=sys.stderr)
            else:
                decision["evidence_persisted"] = True
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    if decision["status"] != "passed":
        return 1
    if decision.get("evidence_persisted") is False:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
