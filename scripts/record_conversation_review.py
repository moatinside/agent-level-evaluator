#!/usr/bin/env python3
"""Record one human calibration answer without editing the model evaluation."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
OUTPUT_ROOT = ROOT / "conversation-review-output"
AXES = [
    "initial_question_capture", "evidence_driven_update", "question_update_rationale",
    "decision_proximity", "feedback_interpretation", "instruction_adherence",
]
STATUSES = {"pass", "partial", "fail", "not_observable"}
CAUSAL_VERDICTS = {"supported", "rejected", "not_observable"}


def _safe_reason(value: str, label: str) -> str:
    # Reuse the evaluator's output guard without depending on its session reader.
    import evaluate_session_with_claude as evaluator
    cleaned = evaluator._safe_output_text(value, label, limit=300)
    assert cleaned is not None
    return cleaned


def _load_evaluation(directory: Path) -> dict[str, Any]:
    path = directory / "evaluation.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 2:
        raise ValueError("unsupported evaluation schema")
    if value.get("evaluation_ref") != directory.name:
        raise ValueError("evaluation reference does not match directory")
    if not isinstance(value.get("input_hash"), str):
        raise ValueError("evaluation input hash is missing")
    return value


def _new_review(evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "comparison_type": "model_vs_human",
        "evaluation_ref": evaluation["evaluation_ref"],
        "input_hash": evaluation["input_hash"],
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "axes": [
            {"axis": axis, "review_status": "pending", "status": None, "reason": None}
            for axis in AXES
        ],
        "causal_reviews": [
            {"change_id": change["change_id"], "review_status": "pending", "verdict": None, "reason": None}
            for change in evaluation["trajectory"]["question_changes"]
        ],
    }


def _load_or_initialize_review(evaluation: dict[str, Any], review_path: Path) -> dict[str, Any]:
    if not review_path.exists():
        return _new_review(evaluation)
    value = json.loads(review_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 2 or value.get("comparison_type") != "model_vs_human":
        raise ValueError("invalid review record")
    if value.get("evaluation_ref") != evaluation["evaluation_ref"] or value.get("input_hash") != evaluation["input_hash"]:
        raise ValueError("review evaluation reference or input hash mismatch")
    if {x.get("axis") for x in value.get("axes", []) if isinstance(x, dict)} != set(AXES):
        raise ValueError("review axes are incomplete")
    expected_changes = {x["change_id"] for x in evaluation["trajectory"]["question_changes"]}
    actual_changes = {x.get("change_id") for x in value.get("causal_reviews", []) if isinstance(x, dict)}
    if expected_changes != actual_changes:
        raise ValueError("review causal update set mismatch")
    return value


def record_axis(directory: Path, axis: str, status: str, reason: str) -> dict[str, Any]:
    evaluation = _load_evaluation(directory)
    if axis not in AXES or status not in STATUSES:
        raise ValueError("invalid axis or status")
    review_path = directory / "review.json"
    review = _load_or_initialize_review(evaluation, review_path)
    entry = next(item for item in review["axes"] if item["axis"] == axis)
    if entry["review_status"] == "recorded":
        raise ValueError("axis already reviewed; refusing to overwrite")
    entry.update({"review_status": "recorded", "status": status, "reason": _safe_reason(reason, "review reason")})
    review["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    _write_json_atomic(review_path, review)
    return {"status": "RECORDED", "evaluation_ref": evaluation["evaluation_ref"], "axis": axis}


def record_causal(directory: Path, change_id: str, verdict: str, reason: str) -> dict[str, Any]:
    evaluation = _load_evaluation(directory)
    if verdict not in CAUSAL_VERDICTS:
        raise ValueError("invalid causal verdict")
    review_path = directory / "review.json"
    review = _load_or_initialize_review(evaluation, review_path)
    entry = next((item for item in review["causal_reviews"] if item["change_id"] == change_id), None)
    if entry is None:
        raise ValueError("unknown causal update")
    if entry["review_status"] == "recorded":
        raise ValueError("causal update already reviewed; refusing to overwrite")
    entry.update({"review_status": "recorded", "verdict": verdict, "reason": _safe_reason(reason, "causal review reason")})
    review["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    _write_json_atomic(review_path, review)
    return {"status": "RECORDED", "evaluation_ref": evaluation["evaluation_ref"], "change_id": change_id}


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".review-", suffix=".tmp", delete=False) as handle:
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
        raise OSError("review record read-back mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description="Record one short human review for a v2 conversation evaluation")
    parser.add_argument("evaluation_dir", type=Path)
    parser.add_argument("--axis", choices=AXES)
    parser.add_argument("--status", choices=sorted(STATUSES))
    parser.add_argument("--reason")
    parser.add_argument("--change-id")
    parser.add_argument("--causal-verdict", choices=sorted(CAUSAL_VERDICTS))
    parser.add_argument("--causal-reason")
    args = parser.parse_args()
    directory = args.evaluation_dir.expanduser().resolve()
    try:
        directory.relative_to(OUTPUT_ROOT.resolve())
    except ValueError:
        raise ValueError("evaluation directory must be under conversation-review-output")
    axis_args = (args.axis, args.status, args.reason)
    causal_args = (args.change_id, args.causal_verdict, args.causal_reason)
    if all(value is not None for value in axis_args) and all(value is None for value in causal_args):
        result = record_axis(directory, args.axis, args.status, args.reason)
    elif all(value is not None for value in causal_args) and all(value is None for value in axis_args):
        result = record_causal(directory, args.change_id, args.causal_verdict, args.causal_reason)
    else:
        raise ValueError("provide either --axis/--status/--reason or --change-id/--causal-verdict/--causal-reason")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
