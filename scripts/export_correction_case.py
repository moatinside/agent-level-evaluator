#!/usr/bin/env python3
"""Export a human-confirmed failure as a sanitized, non-executable case candidate."""
from __future__ import annotations

import argparse
import hashlib
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


def _safe(value: str, name: str) -> str:
    import evaluate_session_with_claude as evaluator
    cleaned = evaluator._safe_output_text(value, name, limit=300)
    assert cleaned is not None
    return cleaned


def build_case(evaluation: dict[str, Any], review: dict[str, Any], *, axis: str, target_position: int, correction_summary: str, expected_behavior: str) -> dict[str, Any]:
    if evaluation.get("schema_version") != 2 or review.get("schema_version") != 2:
        raise ValueError("only v2 evaluation and review records are supported")
    if evaluation.get("evaluation_ref") != review.get("evaluation_ref") or evaluation.get("input_hash") != review.get("input_hash"):
        raise ValueError("evaluation reference or input hash mismatch")
    reviewed = {item.get("axis"): item for item in review.get("axes", []) if isinstance(item, dict)}
    human = reviewed.get(axis)
    if not human or human.get("review_status") != "recorded" or human.get("status") != "fail":
        raise ValueError("a human-recorded fail label is required to create a correction case")
    model_items = {item.get("axis"): item for item in evaluation.get("axes", []) if isinstance(item, dict)}
    if axis not in model_items:
        raise ValueError("unknown evaluation axis")
    target_spans = [span for span in model_items[axis].get("evidence_spans", []) if span.get("position") == target_position and span.get("role") == "assistant"]
    if not target_spans:
        raise ValueError("target position must be an assistant evidence span for the failed axis")
    target_excerpt = target_spans[0]["excerpt"]
    source_spans: list[dict[str, Any]] = []
    trajectory = evaluation.get("trajectory", {})
    for key in ("question_initial", "question_current"):
        source_spans.extend(trajectory.get(key, {}).get("evidence_spans", []))
    for change in trajectory.get("question_changes", []):
        source_spans.extend(change.get("evidence_spans", []))
    for item in evaluation.get("axes", []):
        source_spans.extend(item.get("evidence_spans", []))
    before: dict[tuple[int, int, int], dict[str, Any]] = {}
    for span in source_spans:
        if span.get("position", target_position) < target_position:
            key = (span["position"], span["start"], span["end"])
            before[key] = span
    selected_context = [before[key] for key in sorted(before)][:6]
    context_length = sum(len(item["excerpt"]) for item in selected_context)
    while context_length > 1_200 and selected_context:
        removed = selected_context.pop()
        context_length -= len(removed["excerpt"])
    reason = human.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("human failure reason is required")
    case_seed = f"{evaluation['evaluation_ref']}|{axis}|{target_position}"
    case_ref = hashlib.sha256(case_seed.encode("utf-8")).hexdigest()[:16]
    return {
        "schema_version": 1,
        "case_ref": case_ref,
        "case_kind": "human_confirmed_correction_candidate",
        "source": {"evaluation_ref": evaluation["evaluation_ref"], "input_hash": evaluation["input_hash"], "axis": axis},
        "human_failure": {"status": "fail", "reason": reason},
        "target": {"position": target_position, "actual_behavior_excerpt": target_excerpt},
        "correction_summary": _safe(correction_summary, "correction_summary"),
        "expected_behavior": _safe(expected_behavior, "expected_behavior"),
        "regression_input": {
            "messages_before_target": [{"position": item["position"], "role": item["role"], "excerpt": item["excerpt"]} for item in selected_context],
            "context_status": "pending_context_review" if not selected_context else "excerpts_only_review_required",
            "after_correction_answer_or_label_included": False,
        },
        "post_correction_observation": {"status": "not_observed", "position": None},
        "case_status": "candidate_pending_context_review",
        "execution_status": "not_run",
        "approval_status": "pending",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".case-", suffix=".tmp", delete=False) as handle:
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
        raise OSError("correction case read-back mismatch")


def export_case(directory: Path, *, axis: str, target_position: int, correction_summary: str, expected_behavior: str) -> dict[str, Any]:
    evaluation = json.loads((directory / "evaluation.json").read_text(encoding="utf-8"))
    review = json.loads((directory / "review.json").read_text(encoding="utf-8"))
    case = build_case(evaluation, review, axis=axis, target_position=target_position, correction_summary=correction_summary, expected_behavior=expected_behavior)
    output = directory / "correction-case.json"
    if output.exists():
        raise FileExistsError("correction-case.json already exists; refusing to overwrite")
    _write_atomic(output, case)
    return {"status": "CANDIDATE_CREATED", "case_ref": case["case_ref"], "path": str(output), "case_status": case["case_status"], "execution_status": case["execution_status"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a non-executable regression candidate after a human-confirmed failure")
    parser.add_argument("evaluation_dir", type=Path)
    parser.add_argument("--axis", required=True)
    parser.add_argument("--target-position", type=int, required=True)
    parser.add_argument("--correction-summary", required=True)
    parser.add_argument("--expected-behavior", required=True)
    args = parser.parse_args()
    directory = args.evaluation_dir.expanduser().resolve()
    try:
        directory.relative_to(OUTPUT_ROOT.resolve())
    except ValueError:
        raise ValueError("evaluation directory must be under conversation-review-output")
    result = export_case(directory, axis=args.axis, target_position=args.target_position, correction_summary=args.correction_summary, expected_behavior=args.expected_behavior)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
