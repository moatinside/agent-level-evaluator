#!/usr/bin/env python3
"""Human-auditable views over validated evidence records."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _promotion():
    path = Path(__file__).resolve().parent / "promotion_gate.py"
    spec = importlib.util.spec_from_file_location("_promotion_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load promotion gate")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _classes(value: list[str] | None) -> set[str] | None:
    return set(value) if value else None


def report(root: Path, environment_classes: set[str] | None = None) -> dict[str, Any]:
    gate = _promotion()
    records, stats = gate.collect_records_with_stats(root, environment_classes)
    return {
        "schema_version": 1,
        "environment_classes": sorted(environment_classes or {"production-like", "production"}),
        "records": records,
        "stats": {**stats, "records_considered": len(records)},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--environment-class", action="append", choices=["fixture", "sandbox", "shadow", "production-like", "production"], dest="environment_classes")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="list accepted records")
    group.add_argument("--show", metavar="ASSESSMENT_ID", help="show one accepted record")
    group.add_argument("--summary", action="store_true", help="show counts by level, class, and result")
    args = parser.parse_args()
    result = report(args.root.resolve(), _classes(args.environment_classes))
    if args.show:
        matches = [r for r in result["records"] if r["assessment_id"] == args.show]
        print(json.dumps({"matches": matches, "count": len(matches)}, ensure_ascii=False, indent=2))
        return 0 if matches else 1
    if args.summary:
        summary: dict[str, int] = {}
        for record in result["records"]:
            for key in (f"level:{record['level']}", f"evidence_class:{record['evidence_class']}", f"result:{record['result']}"):
                summary[key] = summary.get(key, 0) + 1
        print(json.dumps({"stats": result["stats"], "summary": summary}, ensure_ascii=False, indent=2))
        return 0
    if args.list:
        print(json.dumps({"records": result["records"], "stats": result["stats"]}, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
