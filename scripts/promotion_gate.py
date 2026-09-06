#!/usr/bin/env python3
"""Apply the evidence-gated promotion rules to evidence records."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_CLASSES = {"D": {"S"}, "F": {"F"}, "X": {"X"}, "O": {"O"}, "P": {"R"}, "S": {"O", "R"}}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for directory in (root / "operational-evidence", root / "evaluation-reports"):
        if not directory.exists():
            continue
        for path in directory.rglob("*.json"):
            try:
                value = load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and "evidence_class" in value:
                records.append(value)
    return records


def assess(root: Path) -> dict[str, Any]:
    records = collect_records(root)
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
            operational_level = level
        else:
            contiguous = False

    for level in (8, 9):
        classes = {r.get("evidence_class") for r in by_level[level] if r.get("result") == "passed"}
        missing = sorted({gate for gate, required in REQUIRED_CLASSES.items() if not (classes & required)})
        allowed = operational_level == 7
        level_results[str(level)] = {
            "track": "advanced",
            "status": "passed" if allowed and not missing else ("blocked_by_level_7" if not allowed else "blocked"),
            "passed_evidence_classes": sorted(x for x in classes if isinstance(x, str)),
            "missing_gates": missing,
            "record_count": len(by_level[level]),
        }

    return {
        "schema_version": 1,
        "decision": "promotion_allowed_only_after_required_evidence_and_human_gate",
        "operational_level": operational_level if operational_level else "unassessed",
        "functional_ceiling": max((level for level in range(1, 10) if any(r.get("evidence_class") == "F" and r.get("result") == "passed" for r in by_level[level])), default="unassessed"),
        "records_considered": len(records),
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
