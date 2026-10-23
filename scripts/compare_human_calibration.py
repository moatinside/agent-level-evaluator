#!/usr/bin/env python3
"""Compare two independent human-calibration result files."""
from __future__ import annotations

import argparse
import json
import re
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
_RATER_REF_RE = re.compile(r"^rater:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def load(path: Path) -> tuple[str, str, dict[str, str]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("scenario_id"), str):
        raise ValueError(f"invalid calibration case: {path}")
    rater_ref = value.get("rater_ref")
    if not isinstance(rater_ref, str) or _RATER_REF_RE.fullmatch(rater_ref) is None:
        raise ValueError("invalid_rater_ref")
    calibration = value.get("human_calibration")
    if not isinstance(calibration, list):
        raise ValueError(f"human_calibration must be an array: {path}")
    labels: dict[str, str] = {}
    for item in calibration:
        if not isinstance(item, dict) or not isinstance(item.get("axis"), str) or not isinstance(item.get("status"), str):
            raise ValueError(f"calibration item is invalid: {path}")
        if item["axis"] in labels:
            raise ValueError("duplicate_calibration_axis")
        labels[item["axis"]] = item["status"]
    if set(labels) != set(AXES) or any(status not in STATUSES for status in labels.values()):
        raise ValueError(f"calibration axes or statuses are incomplete: {path}")
    return value["scenario_id"], rater_ref, labels


def compare(a_path: Path, b_path: Path, *, smoke_only: bool = False) -> dict[str, Any]:
    same_file = a_path.resolve() == b_path.resolve()
    if same_file and not smoke_only:
        raise ValueError("rater_inputs_not_independent")
    scenario_a, rater_a_ref, a = load(a_path)
    scenario_b, rater_b_ref, b = load(b_path)
    if scenario_a != scenario_b:
        raise ValueError(f"scenario_id mismatch: {scenario_a} != {scenario_b}")
    if rater_a_ref == rater_b_ref and not smoke_only:
        raise ValueError("rater_inputs_not_independent")

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
    result = {
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
    if smoke_only:
        result["status"] = "smoke_only"
        result["comparison_type"] = "smoke_only"
        result["reason_code"] = "explicit_smoke_mode"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rater-a", type=Path, required=True)
    parser.add_argument("--rater-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--smoke-only", action="store_true",
        help="label the result smoke_only; never treat it as inter-rater evidence",
    )
    args = parser.parse_args()
    try:
        result = compare(args.rater_a, args.rater_b, smoke_only=args.smoke_only)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": result.get("status", "PASS"), "agreement_rate": result["agreement_rate"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
