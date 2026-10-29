#!/usr/bin/env python3
"""Compare recorded human labels with one versioned model evaluation."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "conversation-review-output"
AXES = [
    "initial_question_capture", "evidence_driven_update", "question_update_rationale",
    "decision_proximity", "feedback_interpretation", "instruction_adherence",
]
VALID = {"pass", "partial", "fail", "not_observable"}
RANK = {"not_observable": 0, "fail": 1, "partial": 2, "pass": 3}


def compare_records(evaluation: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    if evaluation.get("schema_version") != 2 or review.get("schema_version") != 2:
        raise ValueError("only evaluation/review schema v2 is supported")
    if review.get("comparison_type") != "model_vs_human":
        raise ValueError("review comparison_type mismatch")
    if evaluation.get("evaluation_ref") != review.get("evaluation_ref") or evaluation.get("input_hash") != review.get("input_hash"):
        raise ValueError("evaluation reference or input hash mismatch")
    model_items = evaluation.get("axes")
    human_items = review.get("axes")
    if not isinstance(model_items, list) or not isinstance(human_items, list):
        raise ValueError("axis records must be arrays")
    model = {item.get("axis"): item for item in model_items if isinstance(item, dict)}
    human = {item.get("axis"): item for item in human_items if isinstance(item, dict)}
    if set(model) != set(AXES) or set(human) != set(AXES):
        raise ValueError("all six unique axes are required")
    axes: list[dict[str, Any]] = []
    counts = {"agreement": 0, "overcall": 0, "undercall": 0, "unobservable_mismatch": 0}
    pending = 0
    for axis in AXES:
        left = model[axis].get("status")
        if left not in VALID:
            raise ValueError(f"invalid model status for {axis}")
        item = human[axis]
        review_status, right = item.get("review_status"), item.get("status")
        reason = item.get("reason")
        if review_status == "pending":
            if right is not None or reason is not None:
                raise ValueError(f"pending axis {axis} must not contain a label or reason")
            pending += 1
            axes.append({"axis": axis, "model_status": left, "human_status": None, "comparison": "pending"})
            continue
        if review_status != "recorded" or right not in VALID or not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"invalid human review for {axis}")
        if left == right:
            category = "agreement"
        elif "not_observable" in {left, right}:
            category = "unobservable_mismatch"
        elif RANK[left] > RANK[right]:
            category = "overcall"
        else:
            category = "undercall"
        counts[category] += 1
        axes.append({"axis": axis, "model_status": left, "human_status": right, "comparison": category})
    comparable = sum(counts.values())
    causal = review.get("causal_reviews", [])
    if not isinstance(causal, list):
        raise ValueError("causal_reviews must be an array")
    causal_summary = {"pending": 0, "supported": 0, "rejected": 0, "not_observable": 0}
    for item in causal:
        if not isinstance(item, dict):
            raise ValueError("causal review item is invalid")
        if item.get("review_status") == "pending" and item.get("verdict") is None and item.get("reason") is None:
            causal_summary["pending"] += 1
        elif item.get("review_status") == "recorded" and item.get("verdict") in {"supported", "rejected", "not_observable"} and isinstance(item.get("reason"), str) and item["reason"].strip():
            causal_summary[item["verdict"]] += 1
        else:
            raise ValueError("causal review state is inconsistent")
    return {
        "schema_version": 2,
        "comparison_type": "model_vs_human",
        "evaluation_ref": evaluation["evaluation_ref"],
        "input_hash": evaluation["input_hash"],
        "axis_count": comparable,
        "pending_axis_count": pending,
        "agreement_count": counts["agreement"],
        "agreement_rate": counts["agreement"] / comparable if comparable else None,
        "comparison_counts": counts,
        "axes": axes,
        "causal_review_counts": causal_summary,
        "interpretation_boundary": {
            "model_human_comparison": "descriptive_only",
            "causality_proven": False,
            "agent_improvement_proven": False,
            "promotion_decision": "not_authorized",
        },
    }


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".comparison-", suffix=".tmp", delete=False) as handle:
            temp_name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass
    if path.read_text(encoding="utf-8") != text:
        raise OSError("comparison read-back mismatch")


def compare_directory(directory: Path) -> dict[str, Any]:
    evaluation = json.loads((directory / "evaluation.json").read_text(encoding="utf-8"))
    review = json.loads((directory / "review.json").read_text(encoding="utf-8"))
    result = compare_records(evaluation, review)
    _write_atomic(directory / "comparison.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare model labels with the recorded human calibration")
    parser.add_argument("evaluation_dir", type=Path)
    args = parser.parse_args()
    directory = args.evaluation_dir.expanduser().resolve()
    try:
        directory.relative_to(OUTPUT_ROOT.resolve())
    except ValueError:
        raise ValueError("evaluation directory must be under conversation-review-output")
    result = compare_directory(directory)
    print(json.dumps({"status": "OK", "evaluation_ref": result["evaluation_ref"], "compared_axes": result["axis_count"], "pending_axes": result["pending_axis_count"], "agreement_rate": result["agreement_rate"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
