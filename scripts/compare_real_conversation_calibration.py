#!/usr/bin/env python3
"""Compare human calibration across sanitized real-conversation cases."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


AXES = [
    "initial_question_capture",
    "evidence_driven_update",
    "question_update_rationale",
    "decision_proximity",
    "feedback_interpretation",
]
STATUSES = {"pass", "partial", "fail", "not_observable"}


def load_real_case(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"case must be an object: {path}")
    if value.get("source_class") != "real_new_business_brainstorm":
        raise ValueError(f"non-real case supplied: {path}")
    calibration = value.get("human_calibration")
    if not isinstance(calibration, list):
        raise ValueError(f"human_calibration must be an array: {path}")
    by_axis = {item.get("axis"): item.get("status") for item in calibration if isinstance(item, dict)}
    if set(by_axis) != set(AXES) or any(status not in STATUSES for status in by_axis.values()):
        raise ValueError(f"human calibration is incomplete: {path}")
    return value


def compare(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one real case is required")
    cases = [load_real_case(path) for path in paths]
    rows = []
    distributions: dict[str, dict[str, int]] = {}
    for axis in AXES:
        distributions[axis] = dict(Counter(
            next(item["status"] for item in case["human_calibration"] if item["axis"] == axis)
            for case in cases
        ))
    for case in cases:
        calibration = {item["axis"]: item["status"] for item in case["human_calibration"]}
        rows.append({
            "scenario_id": case["scenario_id"],
            "decision_status": case.get("decision_status", "provisionally_locked"),
            "human_calibration": calibration,
            "user_feedback_types": sorted({item["kind"] for item in case["user_feedback"]}),
            "question_change_count": len(case["question_changes"]),
            "semantic_outcome_proven": False,
        })
    return {
        "schema_version": 1,
        "comparison_type": "real_conversation_human_calibration",
        "case_count": len(rows),
        "axes": AXES,
        "rows": rows,
        "status_distribution_by_axis": distributions,
        "interpretation_boundary": {
            "human_calibration": "domain-user assessment of the sanitized conversation case",
            "automatic_agreement": "not_computed; the structural evaluator has no semantic axis verdict",
            "business_effectiveness": "not_proven",
            "synthetic_cases_included": False,
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
