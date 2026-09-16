#!/usr/bin/env python3
"""Evaluate one sanitized real-conversation trajectory in shadow mode.

The fixture contains structure and hashed references only. Raw conversation text,
provider details, and session identifiers are intentionally not persisted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_ref(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def evaluate(case: dict[str, Any], agent_configuration_id: str, evaluator_configuration_id: str) -> dict[str, Any]:
    scenario_id = require_string(case.get("scenario_id"), "scenario_id")
    initial = require_string(case.get("question_initial"), "question_initial")
    current = require_string(case.get("question_current"), "question_current")
    state = require_string(case.get("question_state"), "question_state")
    decision_status = case.get("decision_status", "provisionally_locked")
    if decision_status not in {"provisionally_locked", "on_hold", "no_go", "go"}:
        raise ValueError("unsupported decision_status")
    impact = require_string(case.get("decision_impact"), "decision_impact")
    next_validation = require_string(case.get("next_validation"), "next_validation")
    changes = case.get("question_changes")
    feedback = case.get("user_feedback")
    evidence = case.get("evidence_refs")
    if not isinstance(changes, list) or not changes:
        raise ValueError("question_changes must be a non-empty array")
    if not isinstance(feedback, list) or not feedback:
        raise ValueError("user_feedback must be a non-empty array")
    if not isinstance(evidence, list) or not evidence or not all(isinstance(x, str) and x for x in evidence):
        raise ValueError("evidence_refs must be a non-empty array of references")

    valid_changes = 0
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("each question change must be an object")
        before = require_string(change.get("before_ref"), "question change before_ref")
        after = require_string(change.get("after_ref"), "question change after_ref")
        reason = require_string(change.get("reason"), "question change reason")
        triggered = change.get("triggered_by_evidence_refs")
        if before == after or not isinstance(triggered, list) or not triggered:
            raise ValueError("question change requires distinct refs and evidence")
        valid_changes += 1

    feedback_types = []
    for item in feedback:
        if not isinstance(item, dict):
            raise ValueError("each user feedback item must be an object")
        kind = require_string(item.get("kind"), "user feedback kind")
        basis = require_string(item.get("basis"), "user feedback basis")
        if kind not in {"correction", "acceptance", "positive_signal", "rejection"}:
            raise ValueError("unsupported user feedback kind")
        feedback_types.append(kind)
        if not basis.startswith("feedback:"):
            raise ValueError("user feedback basis must be a reference")

    calibration = case.get("human_calibration")
    if not isinstance(calibration, list) or len(calibration) != 5:
        raise ValueError("human_calibration must contain exactly five assessments")
    calibration_axes = {
        "initial_question_capture",
        "evidence_driven_update",
        "question_update_rationale",
        "decision_proximity",
        "feedback_interpretation",
    }
    calibration_statuses = {"pass", "partial", "fail", "not_observable"}
    normalized_calibration = []
    for item in calibration:
        if not isinstance(item, dict):
            raise ValueError("each human calibration item must be an object")
        axis = require_string(item.get("axis"), "human calibration axis")
        status = require_string(item.get("status"), "human calibration status")
        rationale_ref = require_string(item.get("rationale_ref"), "human calibration rationale_ref")
        if axis not in calibration_axes or status not in calibration_statuses:
            raise ValueError("invalid human calibration axis or status")
        if not rationale_ref.startswith("calibration:"):
            raise ValueError("human calibration rationale_ref must be a reference")
        normalized_calibration.append({"axis": axis, "status": status, "rationale_ref": rationale_ref})
    if {item["axis"] for item in normalized_calibration} != calibration_axes:
        raise ValueError("human calibration axes must be unique and complete")

    scope = case.get("scope_boundary")
    if not isinstance(scope, dict):
        raise ValueError("scope_boundary must be an object")
    scope_status = require_string(scope.get("status"), "scope_boundary status")
    deferred = scope.get("deferred_topics")
    reason_ref = require_string(scope.get("reason_ref"), "scope_boundary reason_ref")
    if scope_status != "intentionally_deferred" or not isinstance(deferred, list) or not deferred or not reason_ref.startswith("scope:"):
        raise ValueError("scope boundary must record intentional deferral and reason")

    acceptance = {
        "trace_present": True,
        "question_initial_present": bool(initial),
        "question_changed": initial != current,
        "question_change_count": valid_changes,
        "evidence_linked_to_change": True,
        "decision_impact_present": bool(impact),
        "decision_status": decision_status,
        "next_validation_present": bool(next_validation),
        "user_feedback_connected": True,
        "user_feedback_types": sorted(set(feedback_types)),
        "raw_text_persisted": False,
        "external_delivery": False,
        "automatic_promotion": False,
        "human_calibration_connected": True,
        "human_calibration_statuses": {item["axis"]: item["status"] for item in normalized_calibration},
        "scope_boundary": scope_status,
        "deferred_topic_count": len(deferred),
    }
    passed = all([
        acceptance["trace_present"],
        acceptance["question_changed"],
        acceptance["evidence_linked_to_change"],
        acceptance["decision_impact_present"],
        acceptance["next_validation_present"],
        acceptance["user_feedback_connected"],
    ])
    result = "passed" if passed else "inconclusive"
    ended = now()
    record = {
        "schema_version": 1,
        "assessment_id": f"real-conversation-shadow-{scenario_id}",
        "level": 1,
        "capability_id": "question_trajectory_update",
        "capability_contract_version": "1.0.0",
        "agent_configuration_id": agent_configuration_id,
        "evaluator_configuration_id": evaluator_configuration_id,
        "evidence_class": "O",
        "scenario_id": scenario_id,
        "trigger_origin": "harness",
        "environment_class": "shadow",
        "execution_mode": "shadow",
        "decision": result,
        "side_effect_status": "not_attempted",
        "started_at": ended,
        "ended_at": ended,
        "input_ref": sha256_ref(case),
        "expected_contract": [
            "trace_question_trajectory",
            "link_question_changes_to_evidence",
            "connect_user_feedback",
            "record_decision_impact_and_next_validation",
            "persist_metadata_only",
        ],
        "action_trace_ref": f"trace:{sha256_ref({'scenario_id': scenario_id, 'changes': changes})[7:]}",
        "validator_report_ref": f"validator:{sha256_ref(acceptance)[7:]}",
        "revision_diff_ref": f"question-change:{sha256_ref(changes)[7:]}",
        "result": result,
        "acceptance_results": acceptance,
        "negative_evidence": [
            {"type": "user_correction_observed", "count": feedback_types.count("correction")},
            {"type": "human_evaluation_not_calibrated", "status": "requires_human_review"},
        ],
        "side_effects": ["no_external_delivery", "no_raw_text_persisted"],
        "rollback_result": "not_required",
        "reviewer": "deterministic",
        "reviewed_at": ended,
    }
    record["integrity_hash"] = sha256_ref(record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agent-configuration-id", required=True)
    parser.add_argument("--evaluator-configuration-id", required=True)
    args = parser.parse_args()
    try:
        case = json.loads(args.case.read_text(encoding="utf-8"))
        if not isinstance(case, dict):
            raise ValueError("case must be an object")
        record = evaluate(case, args.agent_configuration_id, args.evaluator_configuration_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", "result": record["result"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
