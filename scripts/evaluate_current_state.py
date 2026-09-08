#!/usr/bin/env python3
"""Report current Evidence Gate state without running legacy Phase executors.

This is a read-only migration entrypoint. It deliberately does not execute
progression_runner.py, mutate CHECKPOINTS.md, or grant a Level promotion.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evaluate(root: Path) -> dict[str, Any]:
    root = root.resolve()
    audit = load_module("audit_legacy_pipeline", ROOT / "scripts" / "audit_legacy_pipeline.py")
    promotion = load_module("promotion_gate", root / "scripts" / "promotion_gate.py")
    migration = audit.audit(root)
    promotion_result = promotion.assess(root)

    return {
        "schema_version": 1,
        "mode": "current_evidence_read_only",
        "repository": str(root),
        "migration_status": migration["migration_status"],
        "cron_cutover_allowed": migration["cron_cutover_allowed"],
        "migration_blockers": migration["blockers"],
        "evidence": {
            "operational_level": promotion_result["operational_level"],
            "functional_ceiling": promotion_result["functional_ceiling"],
            "records_considered": promotion_result["records_considered"],
            "levels": promotion_result["levels"],
        },
        "promotion": {
            "status": "not_promoted",
            "human_gate_required": True,
            "automatic_promotion": False,
        },
        "legacy_phase_execution": {
            "executed": False,
            "reason": "read-only current-state evaluation does not invoke legacy executors",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate current Evidence Gate state without legacy execution")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = evaluate(args.root)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["migration_status"] == "ready_for_runtime_cutover" else 1


if __name__ == "__main__":
    raise SystemExit(main())
