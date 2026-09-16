#!/usr/bin/env python3
"""Create a metadata-only comparison report for real-conversation cases."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_AXES = {
    "initial_question_capture",
    "evidence_driven_update",
    "question_update_rationale",
    "decision_proximity",
    "feedback_interpretation",
}


def load_case(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"case must be an object: {path}")
    for key in ("scenario_id", "question_initial", "question_current", "decision_impact"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise ValueError(f"missing required field {key}: {path}")
    calibration = value.get("human_calibration")
    if not isinstance(calibration, list):
        raise ValueError(f"human_calibration must be an array: {path}")
    axes = {item.get("axis") for item in calibration if isinstance(item, dict)}
    if axes != REQUIRED_AXES:
        raise ValueError(f"human calibration axes are incomplete: {path}")
    scope = value.get("scope_boundary")
    if not isinstance(scope, dict) or scope.get("status") != "intentionally_deferred":
        raise ValueError(f"intentional scope boundary is required: {path}")
    return value


def summarize(path: Path) -> dict[str, Any]:
    case = load_case(path)
    calibration = {item["axis"]: item["status"] for item in case["human_calibration"]}
    feedback = sorted({item["kind"] for item in case["user_feedback"]})
    scope = case["scope_boundary"]
    non_pass_axes = sorted(axis for axis, status in calibration.items() if status != "pass")
    return {
        "scenario_id": case["scenario_id"],
        "decision_status": case.get("decision_status", "provisionally_locked"),
        "question_initial": case["question_initial"],
        "question_current": case["question_current"],
        "question_change_count": len(case["question_changes"]),
        "human_calibration": calibration,
        "human_non_pass_axes": non_pass_axes,
        "user_feedback_types": feedback,
        "negative_feedback_observed": bool({"rejection", "correction"} & set(feedback)),
        "requires_semantic_review": bool(non_pass_axes or {"rejection", "correction"} & set(feedback)),
        "deferred_topic_count": len(scope["deferred_topics"]),
        "decision_impact": case["decision_impact"],
        "semantic_outcome_proven": False,
        "raw_text_persisted": False,
        "session_id_persisted": False,
    }


def compare(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one case is required")
    rows = [summarize(path) for path in paths]
    statuses = sorted({row["decision_status"] for row in rows})
    return {
        "schema_version": 1,
        "comparison_type": "real_conversation_shadow_metadata",
        "case_count": len(rows),
        "decision_statuses": statuses,
        "rows": rows,
        "interpretation_boundary": {
            "structural_result": "case metadata is complete and comparable",
            "semantic_outcome": "not_proven",
            "business_effectiveness": "not_proven",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compare(args.case)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", "case_count": result["case_count"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
