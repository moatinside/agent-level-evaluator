#!/usr/bin/env python3
"""Turn metadata-first shadow Evidence into pending experience records."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.experience_ledger import append_record, build_record

_FAILURE_BY_RESULT = {
    "passed": "none",
    "blocked": "validation",
    "inconclusive": "unknown",
    "failed": "execution",
}


def to_record(evidence: dict[str, Any]) -> dict[str, Any]:
    result = evidence.get("result")
    if result not in _FAILURE_BY_RESULT:
        raise ValueError("unsupported evidence result")
    run_id = evidence.get("run_id") or evidence.get("assessment_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("evidence requires a run identifier")
    agent_config = evidence.get("agent_configuration_id")
    if not isinstance(agent_config, str) or not agent_config:
        raise ValueError("evidence requires agent_configuration_id")
    refs = [str(evidence[key]) for key in ("assessment_id", "validator_report_ref", "input_ref") if evidence.get(key)]
    if not refs:
        raise ValueError("evidence requires at least one evidence reference")
    experience_suffix = re.sub(r"[^a-zA-Z0-9._-]", "-", run_id)
    summary = f"Shadow evaluation result: {result}; scenario={evidence.get('scenario_id', 'unknown')}"
    return build_record({
        "experience_id": f"experience:{experience_suffix}",
        "task_ref": "task:self-reflection",
        "configuration_id": agent_config if agent_config.startswith("config:") else f"config:{agent_config}",
        "outcome": result,
        "failure_class": _FAILURE_BY_RESULT[result],
        "evidence_refs": refs,
        "lesson": summary,
        "source": "deterministic",
        "created_at": evidence.get("ended_at", "unknown"),
    })


def convert(input_path: Path, output_path: Path) -> dict[str, int]:
    counts = {"read": 0, "written": 0, "rejected": 0}
    for line in input_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        counts["read"] += 1
        try:
            record = to_record(json.loads(line))
            append_record(output_path, record)
            counts["written"] += 1
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            counts["rejected"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        counts = convert(args.input, args.output)
    except OSError as exc:
        print(json.dumps({"status": "inconclusive", "reason": str(exc)}))
        return 1
    print(json.dumps({"status": "PASS", "counts": counts, "output": str(args.output)}, sort_keys=True))
    return 0 if counts["rejected"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
