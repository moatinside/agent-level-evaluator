#!/usr/bin/env python3
"""Collect metadata-first operational evidence from a validated run.

No draft, correction text, or final answer is persisted. Only hashes, statuses,
references, and bounded execution metadata are written to the evidence ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_ref(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def collect(request: dict[str, Any], run_result: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    run_id = require_string(metadata.get("run_id"), "run_id")
    started_at = require_string(metadata.get("started_at"), "started_at")
    ended_at = require_string(metadata.get("ended_at"), "ended_at")
    level = metadata.get("level")
    if not isinstance(level, int) or not 1 <= level <= 9:
        raise ValueError("level must be integer 1..9")

    result = run_result.get("status")
    if result not in {"passed", "failed", "blocked", "inconclusive"}:
        raise ValueError("run result has invalid status")
    attempts = run_result.get("attempts", [])
    if not isinstance(attempts, list):
        raise ValueError("run result attempts must be an array")

    acceptance = {
        "producer_invoked": True,
        "validator_invoked": bool(attempts),
        "correction_invoked": max(0, len(attempts) - 1),
        "revalidation_count": max(0, len(attempts) - 1),
        "delivery_allowed": run_result.get("delivery_allowed") is True,
        "final_status": result,
    }
    negative = []
    if result in {"blocked", "inconclusive", "failed"}:
        negative.append({
            "type": "safe-stop",
            "status": result,
            "reason_code": run_result.get("reason", "not_provided"),
        })

    record = {
        "schema_version": 1,
        "assessment_id": f"{metadata.get('assessment_prefix', 'operational')}-{run_id}",
        "level": level,
        "capability_id": require_string(metadata.get("capability_id"), "capability_id"),
        "capability_contract_version": require_string(metadata.get("capability_contract_version", "1.0.0"), "capability_contract_version"),
        "agent_configuration_id": require_string(metadata.get("agent_configuration_id"), "agent_configuration_id"),
        "evaluator_configuration_id": require_string(metadata.get("evaluator_configuration_id"), "evaluator_configuration_id"),
        "evidence_class": "O",
        "scenario_id": require_string(metadata.get("scenario_id"), "scenario_id"),
        "trigger_origin": metadata.get("trigger_origin", "harness"),
        "environment_class": metadata.get("environment_class", "shadow"),
        "started_at": started_at,
        "ended_at": ended_at,
        "input_ref": sha256_ref(request),
        "expected_contract": metadata.get("expected_contract", ["buffer", "validate", "correct-or-stop", "revalidate", "deliver-only-on-pass"]),
        "action_trace_ref": f"run:{run_id}",
        "validator_report_ref": f"run:{run_id}:validator-summary",
        "revision_diff_ref": f"run:{run_id}:revision-metadata",
        "final_output_ref": f"run:{run_id}:final-output-hash" if result == "passed" else None,
        "result": result,
        "acceptance_results": acceptance,
        "negative_evidence": negative,
        "side_effects": ["no_external_delivery", "no_raw_text_persisted"],
        "rollback_result": "not_required",
        "reviewer": "deterministic",
        "reviewed_at": ended_at,
    }
    record = {key: value for key, value in record.items() if value is not None}
    record["integrity_hash"] = "sha256:" + hashlib.sha256(canonical(record)).hexdigest()
    return record


def append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assessment_id = record["assessment_id"]
    integrity_hash = record.get("integrity_hash")
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            existing = json.loads(line)
            if existing.get("assessment_id") != assessment_id:
                continue
            if existing.get("integrity_hash") == integrity_hash:
                return
            raise ValueError(f"duplicate assessment_id with different integrity_hash: {assessment_id}")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--run-result", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="JSONL evidence ledger")
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        run_result = json.loads(args.run_result.read_text(encoding="utf-8"))
        metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
        if not all(isinstance(value, dict) for value in (request, run_result, metadata)):
            raise ValueError("all inputs must be JSON objects")
        record = collect(request, run_result, metadata)
        append_record(args.output, record)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", "assessment_id": record["assessment_id"], "result": record["result"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
