#!/usr/bin/env python3
"""Run and deterministically verify the Agent Level shadow Evidence batch.

This is intentionally an agent-free boundary: stdout is the cron report and the
process exit code is the authoritative pass/fail signal. Existing JSONL records
are retained; only records appended by this invocation are evaluated.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "tests" / "fixtures" / "shadow-cases.json"
GOOD = ROOT / "tests" / "fixtures" / "producer_good.py"
BAD = ROOT / "tests" / "fixtures" / "producer_bad.py"
CORRECTOR = ROOT / "tests" / "fixtures" / "correction_agent.py"
BATCH_RUNNER = ROOT / "scripts" / "run_shadow_batch.py"
STATE_READER = ROOT / "scripts" / "evaluate_current_state.py"
VALIDATOR = ROOT / "scripts" / "validate_stage1.py"

AGENT_CONFIGURATION_ID = "sha256:9a5419d362256c163fd235dffa0e39ca0f03d7ff94b1f17bff16836279214169"
EXPECTED_COUNTS = {"passed": 2, "blocked": 1, "inconclusive": 1, "failed": 0}
EXPECTED_SCENARIOS = {
    "shadow-clean",
    "shadow-correction",
    "shadow-safe-stop",
    "shadow-inconclusive",
}
FORBIDDEN_KEYS = {"raw_response", "raw_body", "final_text", "draft", "correction_text", "response_text"}
MANIFEST_FILES = (
    "scripts/run_shadow_evidence_guard.py",
    "scripts/run_shadow_batch.py",
    "scripts/validated_command_runner.py",
    "scripts/response_validation.py",
    "scripts/collect_operational_evidence.py",
    "scripts/validate_stage1.py",
    "schemas/evidence-record.schema.json",
    "contracts/level-contracts.yaml",
    "tests/fixtures/shadow-cases.json",
)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def evaluator_configuration_id(root: Path = ROOT) -> str:
    files = []
    for relative in MANIFEST_FILES:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"evaluator manifest file missing: {relative}")
        files.append({"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {
        "kind": "agent-level-shadow-evaluator",
        "manifest_version": 1,
        "files": files,
        "parameters": {"timeout_seconds": 30, "max_iterations": 3, "environment_class": "shadow"},
    }
    return "sha256:" + hashlib.sha256(canonical(manifest)).hexdigest()


def load_validator():
    spec = importlib.util.spec_from_file_location("stage1_validator", VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load stage1 validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {line_number}: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONL line {line_number} is not an object")
        records.append(value)
    return records


def contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key in FORBIDDEN_KEYS or contains_forbidden_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_forbidden_key(item) for item in value)
    return False


def integrity_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("integrity_hash", None)
    return "sha256:" + hashlib.sha256(canonical(payload)).hexdigest()


def result_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in EXPECTED_COUNTS}
    for record in records:
        result = record.get("result")
        if isinstance(result, str) and result in counts:
            counts[result] += 1
    return counts


def validate_new_records(
    all_records: list[dict[str, Any]],
    start_index: int,
    expected_evaluator_id: str,
    validator: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    new_records = all_records[start_index:]

    if len(new_records) != len(EXPECTED_SCENARIOS):
        errors.append(f"new record count must be {len(EXPECTED_SCENARIOS)}, got {len(new_records)}")

    scenario_ids = [record.get("scenario_id") for record in new_records]
    if not all(isinstance(scenario_id, str) and scenario_id for scenario_id in scenario_ids):
        errors.append("new scenario IDs must be non-empty strings")
    elif set(scenario_ids) != EXPECTED_SCENARIOS or len(scenario_ids) != len(set(scenario_ids)):
        errors.append(f"new scenario IDs mismatch: {scenario_ids}")

    for record in new_records:
        scenario = record.get("scenario_id", "unknown")
        validation_errors = validator.validate_evidence(record)
        errors.extend(f"{scenario}: {error}" for error in validation_errors)
        if record.get("evaluator_configuration_id") != expected_evaluator_id:
            errors.append(f"{scenario}: evaluator_configuration_id mismatch")
        if record.get("agent_configuration_id") != AGENT_CONFIGURATION_ID:
            errors.append(f"{scenario}: agent_configuration_id mismatch")
        if record.get("environment_class") != "shadow":
            errors.append(f"{scenario}: environment_class must be shadow")
        if contains_forbidden_key(record):
            errors.append(f"{scenario}: forbidden raw response/body key found")
        if record.get("integrity_hash") != integrity_hash(record):
            errors.append(f"{scenario}: integrity_hash mismatch")

    result_values = [record.get("result") for record in new_records]
    if not all(isinstance(result, str) for result in result_values):
        errors.append("result values must be strings")
    actual_counts = result_counts(new_records)
    if actual_counts != EXPECTED_COUNTS:
        errors.append(f"result counts mismatch: expected {EXPECTED_COUNTS}, got {actual_counts}")
    return new_records, errors


def run_batch(output: Path, evaluator_id: str) -> tuple[int, str]:
    command = [
        sys.executable,
        str(BATCH_RUNNER),
        "--cases",
        str(CASES),
        "--output",
        str(output),
        "--producer-good",
        f"{sys.executable} {GOOD}",
        "--producer-bad",
        f"{sys.executable} {BAD}",
        "--correction",
        f"{sys.executable} {CORRECTOR}",
        "--agent-configuration-id",
        AGENT_CONFIGURATION_ID,
        "--evaluator-configuration-id",
        evaluator_id,
    ]
    try:
        process = subprocess.run(command, text=True, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        return 124, "shadow batch timed out"
    detail = process.stderr.strip() or process.stdout.strip()
    return process.returncode, detail[-500:]


def read_current_state() -> tuple[int, dict[str, Any] | None, str]:
    try:
        process = subprocess.run(
            [sys.executable, str(STATE_READER), "--root", str(ROOT)],
            text=True,
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return 124, None, "current state reader timed out"
    detail = process.stderr.strip() or process.stdout.strip()
    if process.returncode != 0:
        return process.returncode, None, detail[-500:]
    try:
        value = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        return 1, None, f"current state reader returned invalid JSON: {exc.msg}"
    if not isinstance(value, dict):
        return 1, None, "current state reader returned non-object"
    return 0, value, ""


def report(status: str, output: Path, batch_exit: int, state_exit: int, new_records: list[dict[str, Any]], errors: list[str], state: dict[str, Any] | None, evaluator_id: str) -> None:
    actual_counts = result_counts(new_records)
    evidence = (state or {}).get("evidence", {})
    promotion = (state or {}).get("promotion", {})
    print(f"## Agent Level Shadow Evidence Guard: {status}")
    print(f"- 出力: {output}")
    print(f"- Shadow batch終了コード: {batch_exit}")
    print(f"- 新規Evidence: {len(new_records)}件")
    print(f"- 結果: {actual_counts}")
    print(f"- evaluator_configuration_id: {evaluator_id}")
    print(f"- 現行状態読取終了コード: {state_exit}")
    print(f"- operational_level: {evidence.get('operational_level', 'unavailable')}")
    print(f"- functional_ceiling: {evidence.get('functional_ceiling', 'unavailable')}")
    invalid_errors = evidence.get("invalid_record_errors", [])
    print(f"- invalid persisted Evidence: {evidence.get('invalid_record_count', 0)}件")
    for error in invalid_errors[:10]:
        print(f"  - {error}")
    if len(invalid_errors) > 10:
        print(f"  - ...ほか{len(invalid_errors) - 10}件")
    print(f"- promotion.status: {promotion.get('status', 'unavailable')}")
    print("- raw response/body: 検出なし" if not any(contains_forbidden_key(record) for record in new_records) else "- raw response/body: 検出あり")
    if errors:
        print("- 契約エラー:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("- 契約エラー: 0件")
    print("- Evidenceは自動昇格に使用しない")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="JSONL output; defaults to today's shadow file")
    parser.add_argument("--verify-only", action="store_true", help="verify an existing file without running the batch")
    parser.add_argument("--start-index", type=int, help="record index from which verification starts")
    args = parser.parse_args()

    output = args.output or ROOT / "operational-evidence" / "shadow" / f"{datetime.now().astimezone().date().isoformat()}-cron-shadow.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    batch_exit = 0
    state_exit = 0
    state: dict[str, Any] | None = None
    before_count = 0
    evaluator_id = "unavailable"
    new_records: list[dict[str, Any]] = []

    try:
        evaluator_id = evaluator_configuration_id()
        before_count = len(read_records(output)) if not args.verify_only else (args.start_index or 0)
        if args.verify_only:
            all_records = read_records(output)
        else:
            batch_exit, batch_detail = run_batch(output, evaluator_id)
            if batch_exit != 0:
                errors.append(f"shadow batch failed: exit={batch_exit} detail={batch_detail}")
            all_records = read_records(output)
        validator = load_validator()
        new_records, validation_errors = validate_new_records(all_records, before_count, evaluator_id, validator)
        errors.extend(validation_errors)
        state_exit, state, state_detail = read_current_state()
        if state_exit != 0:
            errors.append(f"current state read failed: exit={state_exit} detail={state_detail}")
    except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        errors.append(str(exc))

    status = "PASS" if not errors else "CONTRACT_FAIL"
    report(status, output, batch_exit, state_exit, new_records, errors, state, evaluator_id)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
