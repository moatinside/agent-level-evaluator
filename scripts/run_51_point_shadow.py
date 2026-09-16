#!/usr/bin/env python3
"""Run an isolated, deterministic shadow probe for the provisional 51-point gate.

This is a contract probe, not proof of agent capability. It records only
metadata and gate outcomes; no answer text or external side effect is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_operational_evidence import append_record, collect  # noqa: E402

AXES = ("decision_relevance", "evidence_change", "reversibility", "human_alignment", "safety")


def timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def assess_gate(gate: dict[str, Any]) -> tuple[str, str, dict[str, str]]:
    states: dict[str, str] = {}
    for axis in AXES:
        value = gate.get(axis)
        states[axis] = "pass" if value is True else "fail" if value is False else "unknown"
    if states["safety"] == "fail":
        return "blocked", "safety_veto", states
    if "unknown" in states.values():
        return "inconclusive", "gate_axis_unobserved", states
    if "fail" in states.values():
        return "failed", "minimum_gate_not_met", states
    return "passed", "all_minimum_axes_pass", states


def make_record(case: dict[str, Any], agent_id: str, evaluator_id: str, index: int) -> dict[str, Any]:
    gate = case.get("gate")
    if not isinstance(gate, dict):
        raise ValueError(f"{case.get('case_id')}: gate must be an object")
    result, reason, states = assess_gate(gate)
    run_id = f"51-point-{index:04d}-{case['case_id']}"
    now = timestamp()
    request = {"scenario": case["case_id"], "input": case.get("input", "synthetic business hypothesis")}
    run_result = {"status": result, "delivery_allowed": False, "attempts": [{"gate": states}], "reason": reason}
    metadata = {
        "run_id": run_id,
        "assessment_prefix": "shadow-51",
        # Evidence schema requires a 1..9 level; this probe does not promote it.
        "level": 1,
        "capability_id": "provisional_51_point_gate",
        "capability_contract_version": "0.1.0",
        "agent_configuration_id": agent_id,
        "evaluator_configuration_id": evaluator_id,
        "scenario_id": case["case_id"],
        "trigger_origin": "harness",
        "environment_class": "shadow",
        "execution_mode": "shadow",
        "started_at": now,
        "ended_at": now,
        "expected_contract": list(AXES) + ["no_external_delivery"],
    }
    record = collect(request, run_result, metadata)
    record["acceptance_results"]["51_point_gate"] = {
        "status": result,
        "reason": reason,
        "axes": states,
        "human_review": case.get("human_review", "not_requested"),
        "human_review_is_not_auto_promotion": True,
    }
    # Recompute integrity after adding the gate details.
    from collect_operational_evidence import canonical
    record["integrity_hash"] = "sha256:" + hashlib.sha256(canonical({k: v for k, v in record.items() if k != "integrity_hash"})).hexdigest()
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agent-configuration-id", required=True)
    parser.add_argument("--evaluator-configuration-id", required=True)
    args = parser.parse_args()
    try:
        cases = json.loads(args.cases.read_text(encoding="utf-8"))
        if not isinstance(cases, list) or not cases:
            raise ValueError("cases must be a non-empty JSON array")
        counts = {"total": 0, "passed": 0, "failed": 0, "blocked": 0, "inconclusive": 0}
        for index, case in enumerate(cases, 1):
            if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
                raise ValueError(f"case {index} must contain case_id")
            record = make_record(case, args.agent_configuration_id, args.evaluator_configuration_id, index)
            append_record(args.output, record)
            counts[record["result"]] += 1
            counts["total"] += 1
        print(json.dumps({"status": "PASS", "counts": counts, "output": str(args.output)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
