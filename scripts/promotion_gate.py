#!/usr/bin/env python3
"""Apply evidence-gated promotion rules to validated evidence records."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "scripts" / "validate_stage1.py"
REQUIRED_CLASSES = {"D": {"S"}, "F": {"F"}, "X": {"X"}, "O": {"O"}, "P": {"R"}, "S": {"O", "R"}}
FORBIDDEN_KEYS = {"raw_response", "raw_body", "final_text", "draft", "correction_text", "response_text"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def integrity_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("integrity_hash", None)
    return "sha256:" + hashlib.sha256(canonical(payload)).hexdigest()


def contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key in FORBIDDEN_KEYS or contains_forbidden_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_forbidden_key(item) for item in value)
    return False


def expected_evaluator_configuration_id(root: Path) -> tuple[str | None, str | None]:
    guard_path = root / "scripts" / "run_shadow_evidence_guard.py"
    if not guard_path.is_file():
        return None, None
    try:
        guard = load_module("_shadow_guard_for_promotion", guard_path)
        return guard.evaluator_configuration_id(root), None
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        return None, f"evaluator configuration manifest unavailable: {type(exc).__name__}"


def validate_persisted_record(
    record: dict[str, Any],
    validator: Any,
    expected_evaluator_id: str | None,
) -> list[str]:
    errors = list(validator.validate_evidence(record))
    if contains_forbidden_key(record):
        errors.append("forbidden raw response/body key found")
    if record.get("integrity_hash") != integrity_hash(record):
        errors.append("integrity_hash mismatch")
    if expected_evaluator_id is not None and record.get("evaluator_configuration_id") != expected_evaluator_id:
        errors.append("evaluator_configuration_id mismatch")
    return errors


def collect_records(
    root: Path,
    invalid_errors: list[str] | None = None,
    invalid_locations: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Read only valid evidence records and report invalid persisted records."""
    errors = invalid_errors if invalid_errors is not None else []
    locations = invalid_locations if invalid_locations is not None else []
    validator = load_module("_stage1_validator_for_promotion", VALIDATOR)
    expected_id, configuration_error = expected_evaluator_configuration_id(root)
    if configuration_error:
        errors.append(configuration_error)
        return []

    records: list[dict[str, Any]] = []
    for directory in (root / "operational-evidence", root / "evaluation-reports"):
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.suffix not in {".json", ".jsonl"} or not path.is_file():
                continue
            relative = path.relative_to(root)
            candidates: list[tuple[int, Any]] = []
            if path.suffix == ".jsonl":
                for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                    if not line.strip():
                        continue
                    try:
                        candidates.append((line_number, json.loads(line)))
                    except json.JSONDecodeError as exc:
                        location = f"{relative}:{line_number}"
                        locations.append(location)
                        errors.append(f"{location}: invalid JSON: {exc.msg}")
            else:
                try:
                    candidates.append((1, load_json(path)))
                except (OSError, json.JSONDecodeError) as exc:
                    location = str(relative)
                    locations.append(location)
                    errors.append(f"{location}: invalid JSON: {type(exc).__name__}")

            for line_number, value in candidates:
                location = f"{relative}:{line_number}" if path.suffix == ".jsonl" else str(relative)
                if not isinstance(value, dict):
                    locations.append(location)
                    errors.append(f"{location}: evidence record must be an object")
                    continue
                if "evidence_class" not in value:
                    continue
                validation_errors = validate_persisted_record(value, validator, expected_id)
                if validation_errors:
                    locations.append(location)
                    errors.extend(f"{location}: {error}" for error in validation_errors)
                    continue
                records.append(value)
    return records


def assess(root: Path) -> dict[str, Any]:
    invalid_errors: list[str] = []
    invalid_locations: list[str] = []
    records = collect_records(root, invalid_errors, invalid_locations)
    by_level: dict[int, list[dict[str, Any]]] = {level: [] for level in range(1, 10)}
    for record in records:
        level = record.get("level")
        if isinstance(level, int) and level in by_level:
            by_level[level].append(record)

    level_results: dict[str, Any] = {}
    computed_operational_level = 0
    contiguous = True
    for level in range(1, 8):
        classes = {r.get("evidence_class") for r in by_level[level] if r.get("result") == "passed"}
        missing = sorted({gate for gate, required in REQUIRED_CLASSES.items() if not (classes & required)})
        if not contiguous:
            status = "blocked_by_lower_level"
        else:
            status = "passed" if not missing else "blocked"
        level_results[str(level)] = {
            "track": "core",
            "status": status,
            "passed_evidence_classes": sorted(x for x in classes if isinstance(x, str)),
            "missing_gates": missing,
            "record_count": len(by_level[level]),
        }
        if status == "passed":
            computed_operational_level = level
        else:
            contiguous = False

    for level in (8, 9):
        classes = {r.get("evidence_class") for r in by_level[level] if r.get("result") == "passed"}
        missing = sorted({gate for gate, required in REQUIRED_CLASSES.items() if not (classes & required)})
        allowed = computed_operational_level == 7
        level_results[str(level)] = {
            "track": "advanced",
            "status": "passed" if allowed and not missing else ("blocked_by_level_7" if not allowed else "blocked"),
            "passed_evidence_classes": sorted(x for x in classes if isinstance(x, str)),
            "missing_gates": missing,
            "record_count": len(by_level[level]),
        }

    functional_ceiling = max(
        (level for level in range(1, 10) if any(r.get("evidence_class") == "F" and r.get("result") == "passed" for r in by_level[level])),
        default="unassessed",
    )
    return {
        "schema_version": 1,
        "decision": "promotion_allowed_only_after_required_evidence_and_human_gate",
        "operational_level": computed_operational_level if computed_operational_level else "unassessed",
        "functional_ceiling": functional_ceiling,
        "records_considered": len(records),
        "invalid_record_count": len(invalid_locations),
        "invalid_record_errors": invalid_errors,
        "levels": level_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = assess(args.root.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
