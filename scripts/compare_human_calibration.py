#!/usr/bin/env python3
"""Compare two independent human-calibration result files."""
from __future__ import annotations

import argparse
import json
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
RANK = {"not_observable": 0, "fail": 1, "partial": 2, "pass": 3}


def load(path: Path) -> tuple[str, dict[str, str]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("scenario_id"), str):
        raise ValueError(f"invalid calibration case: {path}")
    calibration = value.get("human_calibration")
    if not isinstance(calibration, list):
        raise ValueError(f"human_calibration must be an array: {path}")
    labels: dict[str, str] = {}
    for item in calibration:
        if not isinstance(item, dict) or not isinstance(item.get("axis"), str) or not isinstance(item.get("status"), str):
            raise ValueError(f"calibration item is invalid: {path}")
        labels[item["axis"]] = item["status"]
    if set(labels) != set(AXES) or any(status not in STATUSES for status in labels.values()):
        raise ValueError(f"calibration axes or statuses are incomplete: {path}")
    return value["scenario_id"], labels


def compare(a_path: Path, b_path: Path) -> dict[str, Any]:
    scenario_a, a = load(a_path)
    scenario_b, b = load(b_path)
    if scenario_a != scenario_b:
        raise ValueError(f"scenario_id mismatch: {scenario_a} != {scenario_b}")
    axes: list[dict[str, str]] = []
    counts = {"agreement": 0, "overcall": 0, "undercall": 0, "unobservable_mismatch": 0}
    for axis in AXES:
        left, right = a[axis], b[axis]
        if left == right:
            category = "agreement"
        elif "not_observable" in {left, right}:
            category = "unobservable_mismatch"
        elif RANK[left] > RANK[right]:
            category = "overcall"
        else:
            category = "undercall"
        counts[category] += 1
        axes.append({"axis": axis, "rater_a": left, "rater_b": right, "comparison": category})
    return {
        "schema_version": 1,
        "comparison_type": "human_calibration_inter_rater",
        "scenario_id": scenario_a,
        "axis_count": len(axes),
        "agreement_count": counts["agreement"],
        "agreement_rate": counts["agreement"] / len(axes),
        "comparison_counts": counts,
        "axes": axes,
        "interpretation_boundary": {
            "rater_agreement": "descriptive_only",
            "business_effectiveness": "not_proven",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rater-a", type=Path, required=True)
    parser.add_argument("--rater-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compare(args.rater_a, args.rater_b)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", "agreement_rate": result["agreement_rate"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
