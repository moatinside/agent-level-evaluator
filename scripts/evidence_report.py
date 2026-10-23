#!/usr/bin/env python3
"""Human-auditable views over validated evidence records."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
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


def _runtime_transport_module():
    path = Path(__file__).resolve().parent / "runtime_evidence_transport_report.py"
    spec = importlib.util.spec_from_file_location("_runtime_evidence_transport_report", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load runtime transport report")
    module = importlib.util.module_from_spec(spec)
    root_text = str(ROOT)
    inserted_root = root_text not in sys.path
    if inserted_root:
        sys.path.insert(0, root_text)
    try:
        spec.loader.exec_module(module)
    finally:
        if inserted_root:
            sys.path.remove(root_text)
    return module


class RuntimeTransportReportError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _build_runtime_transport_report(
    outbox_db_path: Path,
    ledger_db_path: Path,
    sink_id: str,
    max_records: int,
) -> dict[str, Any]:
    module = _runtime_transport_module()
    try:
        return module.build_runtime_evidence_transport_report(
            outbox_db_path,
            ledger_db_path,
            sink_id=sink_id,
            max_records=max_records,
        )
    except (module.ConsumerError, module.RuntimeEvidenceReportError) as exc:
        raise RuntimeTransportReportError(exc.code) from None


def report(
    root: Path,
    environment_classes: set[str] | None = None,
    *,
    runtime_outbox_db_path: Path | None = None,
    runtime_ledger_db_path: Path | None = None,
    runtime_sink_id: str | None = None,
    runtime_max_records: int | None = None,
) -> dict[str, Any]:
    runtime_options = (
        runtime_outbox_db_path,
        runtime_ledger_db_path,
        runtime_sink_id,
        runtime_max_records,
    )
    has_runtime_options = any(value is not None for value in runtime_options)
    if has_runtime_options and any(value is None for value in runtime_options):
        raise ValueError("all four runtime transport arguments must be supplied together")

    gate = _promotion()
    records, stats = gate.collect_records_with_stats(root, environment_classes)
    result = {
        "schema_version": 1,
        "environment_classes": sorted(environment_classes or {"production-like", "production"}),
        "records": records,
        "stats": {**stats, "records_considered": len(records)},
    }
    if has_runtime_options:
        assert runtime_outbox_db_path is not None
        assert runtime_ledger_db_path is not None
        assert runtime_sink_id is not None
        assert runtime_max_records is not None
        result["runtime_transport"] = _build_runtime_transport_report(
            runtime_outbox_db_path,
            runtime_ledger_db_path,
            runtime_sink_id,
            runtime_max_records,
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--environment-class", action="append", choices=["fixture", "sandbox", "shadow", "production-like", "production"], dest="environment_classes")
    parser.add_argument("--runtime-outbox-db", type=Path)
    parser.add_argument("--runtime-ledger-db", type=Path)
    parser.add_argument("--runtime-sink-id")
    parser.add_argument("--runtime-max-records", type=int)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="list accepted records")
    group.add_argument("--show", metavar="ASSESSMENT_ID", help="show one accepted record")
    group.add_argument("--summary", action="store_true", help="show counts by level, class, and result")
    args = parser.parse_args()

    runtime_options = (
        args.runtime_outbox_db,
        args.runtime_ledger_db,
        args.runtime_sink_id,
        args.runtime_max_records,
    )
    if any(value is not None for value in runtime_options) and any(
        value is None for value in runtime_options
    ):
        parser.error("all four --runtime-* arguments must be supplied together")

    try:
        result = report(
            args.root.resolve(),
            _classes(args.environment_classes),
            runtime_outbox_db_path=args.runtime_outbox_db,
            runtime_ledger_db_path=args.runtime_ledger_db,
            runtime_sink_id=args.runtime_sink_id,
            runtime_max_records=args.runtime_max_records,
        )
    except RuntimeTransportReportError as exc:
        print(json.dumps({"status": "error", "error_code": exc.code}, sort_keys=True))
        return 2

    def include_transport(output: dict[str, Any]) -> dict[str, Any]:
        if "runtime_transport" in result:
            output["runtime_transport"] = result["runtime_transport"]
        return output

    if args.show:
        matches = [r for r in result["records"] if r["assessment_id"] == args.show]
        print(json.dumps(include_transport({"matches": matches, "count": len(matches)}), ensure_ascii=False, indent=2))
        return 0 if matches else 1
    if args.summary:
        summary: dict[str, int] = {}
        for record in result["records"]:
            for key in (f"level:{record['level']}", f"evidence_class:{record['evidence_class']}", f"result:{record['result']}"):
                summary[key] = summary.get(key, 0) + 1
        print(json.dumps(include_transport({"stats": result["stats"], "summary": summary}), ensure_ascii=False, indent=2))
        return 0
    if args.list:
        print(json.dumps(include_transport({"records": result["records"], "stats": result["stats"]}), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
