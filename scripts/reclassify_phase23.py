#!/usr/bin/env python3
"""Reclassify legacy Phase 2.3 evidence without promoting Agent Levels."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def classify(source_root: Path) -> dict[str, Any]:
    phase_root = source_root / "execution-evidence" / "2.3"
    state_path = phase_root / "state.json"
    state = load_json(state_path) if state_path.exists() else {}
    run_records: list[dict[str, Any]] = []
    run_dir = phase_root / "runs"
    for path in sorted(run_dir.glob("*.json")) if run_dir.exists() else []:
        record = load_json(path)
        run_records.append({
            "source": str(path),
            "date": record.get("date"),
            "candidate": record.get("candidate"),
            "evidence_classes": ["O"],
            "phase_capability": "scheduled_phase_executor",
            "level_capability": "level_2_workflow_candidate",
            "novel_claim": record.get("novel"),
            "verifiable_claim": record.get("verifiable"),
            "novelty_is_independent": False,
            "notes": [
                "The run proves scheduled executor activity, not autonomous Agent behavior.",
                "The candidate is evaluated by the phase script's deterministic history comparison.",
            ],
        })
        if record.get("novel") is False:
            run_records[-1]["evidence_classes"].append("N")
            run_records[-1]["notes"].append("Duplicate/non-novel result is retained as negative evidence.")
        if record.get("verifiable") is True:
            run_records[-1]["notes"].append("verifiable=true is a script-produced claim, not independent verification.")

    phase_status = state.get("status", "missing")
    return {
        "schema_version": 1,
        "reclassification_version": "1.0.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "source_phase": "2.3",
        "legacy_phase_status": phase_status,
        "legacy_phase_completion": phase_status == "passed",
        "promotion_eligible": False,
        "operational_level_impact": {
            "level_2": "candidate_evidence_only",
            "level_5": "not_proven",
            "level_6": "not_proven",
            "level_7": "not_proven",
        },
        "summary": {
            "run_count": len(run_records),
            "novel_run_count": sum(1 for r in run_records if r.get("novel_claim") is True),
            "duplicate_run_count": sum(1 for r in run_records if r.get("novel_claim") is False),
            "predeclared_candidate_count": len({r.get("candidate") for r in run_records if r.get("candidate")}),
        },
        "records": run_records,
        "decision": "Keep Phase 2.3 history unchanged; do not connect it to Level promotion.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = classify(args.source_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "source_phase": "2.3",
        "legacy_phase_status": result["legacy_phase_status"],
        "promotion_eligible": result["promotion_eligible"],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
