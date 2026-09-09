#!/usr/bin/env python3
"""Validate Stage 1 level contracts and evidence records without jsonschema."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required") from exc

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts" / "level-contracts.yaml"
SCHEMA = ROOT / "schemas" / "evidence-record.schema.json"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
EVIDENCE_CLASSES = {"S", "F", "X", "O", "R", "N"}
RESULTS = {"passed", "failed", "blocked", "inconclusive"}


def load_contracts() -> dict:
    value = yaml.safe_load(CONTRACTS.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("contracts must be an object")
    return value


def validate_contracts(doc: dict) -> list[str]:
    errors: list[str] = []
    if doc.get("schema_version") != 1:
        errors.append("contract schema_version must be 1")
    gate_ids = [g.get("id") for g in doc.get("gates", [])]
    if gate_ids != ["D", "F", "X", "O", "P", "S"]:
        errors.append(f"gate ids must be D,F,X,O,P,S; got {gate_ids}")
    levels = doc.get("levels")
    if not isinstance(levels, list) or len(levels) != 9:
        errors.append("exactly 9 level contracts are required")
        return errors
    ids = [item.get("level") for item in levels]
    if ids != list(range(1, 10)):
        errors.append(f"level ids must be 1..9; got {ids}")
    for item in levels:
        level = item.get("level")
        required = ["capability_id", "track", "prerequisites", "contract", "functional", "failure_recovery", "operational"]
        for key in required:
            if key not in item:
                errors.append(f"level {level}: missing {key}")
        if level in range(1, 8) and item.get("track") != "core":
            errors.append(f"level {level}: track must be core")
        if level in (8, 9) and item.get("track") != "advanced":
            errors.append(f"level {level}: track must be advanced")
        if level in (8, 9) and item.get("prerequisites") != [7]:
            errors.append(f"level {level}: advanced prerequisite must be [7]")
    rules = doc.get("promotion_rules", {})
    for key in ["self_report_alone", "static_readiness_alone", "core_levels_contiguous", "automatic_promotion"]:
        if key not in rules:
            errors.append(f"missing promotion rule: {key}")
    if rules.get("self_report_alone") is not False:
        errors.append("self_report_alone must be false")
    if rules.get("static_readiness_alone") is not False:
        errors.append("static_readiness_alone must be false")
    return errors


def validate_schema_file() -> list[str]:
    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"schema is invalid JSON: {exc}"]
    errors = []
    for key in ["$schema", "type", "required", "properties"]:
        if key not in schema:
            errors.append(f"schema missing {key}")
    if schema.get("type") != "object":
        errors.append("schema root type must be object")
    return errors


def validate_evidence(record: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["evidence must be an object"]
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    allowed = set(schema.get("properties", {}))
    unknown = sorted(set(record) - allowed)
    if unknown:
        errors.append(f"unknown evidence fields: {', '.join(unknown)}")
    required = [
        "schema_version", "assessment_id", "level", "capability_id",
        "capability_contract_version", "agent_configuration_id",
        "evaluator_configuration_id", "evidence_class", "scenario_id",
        "trigger_origin", "environment_class", "started_at", "ended_at",
        "input_ref", "expected_contract", "result", "reviewer",
        "integrity_hash",
    ]
    for key in required:
        if key not in record:
            errors.append(f"evidence missing {key}")
    if errors:
        return errors
    if record["schema_version"] != 1:
        errors.append("evidence schema_version must be 1")
    for key in ["assessment_id", "capability_id", "capability_contract_version", "scenario_id", "input_ref"]:
        if not isinstance(record[key], str) or not record[key]:
            errors.append(f"{key} must be a non-empty string")
    if not re.fullmatch(r"^[a-z][a-z0-9_]+$", record["capability_id"]):
        errors.append("capability_id has invalid format")
    if not isinstance(record["level"], int) or not 1 <= record["level"] <= 9:
        errors.append("level must be integer 1..9")
    if record["evidence_class"] not in EVIDENCE_CLASSES:
        errors.append("invalid evidence_class")
    if record["result"] not in RESULTS:
        errors.append("invalid result")
    if record["trigger_origin"] not in {"user", "agent", "harness", "cron"}:
        errors.append("invalid trigger_origin")
    if record["environment_class"] not in {"fixture", "sandbox", "shadow", "production-like", "production"}:
        errors.append("invalid environment_class")
    if record["reviewer"] not in {"deterministic", "independent-agent", "human"}:
        errors.append("invalid reviewer")
    for key in ["agent_configuration_id", "evaluator_configuration_id", "integrity_hash"]:
        if not isinstance(record[key], str) or not HASH_RE.fullmatch(record[key]):
            errors.append(f"{key} must be sha256:<64 lowercase hex>")
    without_hash = {key: value for key, value in record.items() if key != "integrity_hash"}
    expected_hash = "sha256:" + hashlib.sha256(
        json.dumps(without_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if record["integrity_hash"] != expected_hash:
        errors.append("integrity_hash does not match record")
    if not isinstance(record["expected_contract"], list) or not record["expected_contract"]:
        errors.append("expected_contract must be a non-empty array")
    if record["evidence_class"] == "O" and not record.get("action_trace_ref"):
        errors.append("O evidence requires action_trace_ref")
    if record["evidence_class"] == "F" and not isinstance(record.get("acceptance_results"), dict):
        errors.append("F evidence requires acceptance_results")
    for key in ["started_at", "ended_at"]:
        try:
            datetime.fromisoformat(record[key].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            errors.append(f"{key} must be RFC3339-like datetime")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    errors = validate_contracts(load_contracts()) + validate_schema_file()
    if args.evidence:
        try:
            record = json.loads(args.evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cannot load evidence: {exc}")
        else:
            errors.extend(validate_evidence(record))
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": "PASS", "contracts": "valid", "schema": "valid", "evidence": "validated" if args.evidence else "not_requested"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
