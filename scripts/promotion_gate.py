#!/usr/bin/env python3
"""Apply evidence-gated promotion rules to validated evidence records."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_CLASSES = {"D": {"S"}, "F": {"F"}, "X": {"X"}, "O": {"O"}, "P": {"R"}, "S": {"O", "R"}}


def _validator():
    path = Path(__file__).resolve().parent / "validate_stage1.py"
    spec = importlib.util.spec_from_file_location("_evidence_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load evidence validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_paths(root: Path):
    for directory in (root / "operational-evidence", root / "evaluation-reports"):
        if directory.exists():
            yield from sorted(directory.rglob("*.json"))
            yield from sorted(directory.rglob("*.jsonl"))


def collect_records_with_stats(root: Path, environment_classes: set[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    validator = _validator()
    eligible = environment_classes or {"production-like", "production"}
    records: list[dict[str, Any]] = []
    stats = {"files_scanned": 0, "lines_scanned": 0, "records_eligible_scanned": 0, "records_excluded_environment": 0, "records_rejected": 0, "records_duplicate": 0, "records_conflict": 0}
    seen: dict[str, str] = {}
    conflicted: set[str] = set()
    for path in _iter_paths(root):
        stats["files_scanned"] += 1
        try:
            if path.suffix == ".jsonl":
                values = []
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    stats["lines_scanned"] += 1
                    try:
                        values.append(json.loads(line))
                    except json.JSONDecodeError:
                        stats["records_rejected"] += 1
            else:
                values = [load_json(path)]
                stats["lines_scanned"] += 1
        except (OSError, UnicodeError, json.JSONDecodeError):
            stats["records_rejected"] += 1
            continue
        for value in values:
            if not isinstance(value, dict) or "evidence_class" not in value:
                stats["records_rejected"] += 1
                continue
            if validator.validate_evidence(value):
                stats["records_rejected"] += 1
                continue
            if value["environment_class"] not in eligible:
                stats["records_excluded_environment"] += 1
                continue
            stats["records_eligible_scanned"] += 1
            assessment_id = value["assessment_id"]
            if assessment_id in conflicted:
                stats["records_rejected"] += 1
                continue
            if assessment_id in seen:
                if seen[assessment_id] == value.get("integrity_hash"):
                    stats["records_duplicate"] += 1
                else:
                    stats["records_conflict"] += 1
                    stats["records_rejected"] += 1
                    conflicted.add(assessment_id)
                    records[:] = [r for r in records if r["assessment_id"] != assessment_id]
                    seen.pop(assessment_id, None)
                continue
            seen[assessment_id] = str(value.get("integrity_hash"))
            records.append(value)
    return records, stats


def collect_records(root: Path) -> list[dict[str, Any]]:
    return collect_records_with_stats(root)[0]


def assess(root: Path, environment_classes: set[str] | None = None) -> dict[str, Any]:
    records, stats = collect_records_with_stats(root, environment_classes)
    by_level: dict[int, list[dict[str, Any]]] = {level: [] for level in range(1, 10)}
    for record in records:
        level = record.get("level")
        if isinstance(level, int) and level in by_level:
            by_level[level].append(record)

    level_results: dict[str, Any] = {}
    operational_level = 0
    contiguous = True
    for level in range(1, 8):
        classes = {r.get("evidence_class") for r in by_level[level] if r.get("result") == "passed"}
        missing = sorted({gate for gate, required in REQUIRED_CLASSES.items() if not (classes & required)})
        status = "blocked_by_lower_level" if not contiguous else ("passed" if not missing else "blocked")
        level_results[str(level)] = {"track": "core", "status": status, "passed_evidence_classes": sorted(x for x in classes if isinstance(x, str)), "missing_gates": missing, "record_count": len(by_level[level])}
        if status == "passed":
            operational_level = level
        else:
            contiguous = False
    for level in (8, 9):
        classes = {r.get("evidence_class") for r in by_level[level] if r.get("result") == "passed"}
        missing = sorted({gate for gate, required in REQUIRED_CLASSES.items() if not (classes & required)})
        allowed = operational_level == 7
        level_results[str(level)] = {"track": "advanced", "status": "passed" if allowed and not missing else ("blocked_by_level_7" if not allowed else "blocked"), "passed_evidence_classes": sorted(x for x in classes if isinstance(x, str)), "missing_gates": missing, "record_count": len(by_level[level])}
    return {"schema_version": 1, "decision": "promotion_allowed_only_after_required_evidence_and_human_gate", "operational_level": operational_level if operational_level else "unassessed", "functional_ceiling": max((level for level in range(1, 10) if any(r.get("evidence_class") == "F" and r.get("result") == "passed" for r in by_level[level])), default="unassessed"), "records_considered": len(records), "accepted_assessment_ids": [r["assessment_id"] for r in records], **stats, "levels": level_results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--environment-class", action="append", choices=["fixture", "sandbox", "shadow", "production-like", "production"], dest="environment_classes", help="include only these evidence environments; defaults to production-like and production")
    args = parser.parse_args()
    result = assess(args.root.resolve(), set(args.environment_classes) if args.environment_classes else None)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
