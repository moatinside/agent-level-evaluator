#!/usr/bin/env python3
"""Audit whether a repository still exposes the legacy Phase executor path.

This is an audit-only command. It never edits checkpoints, evidence, or cron
configuration. A repository may retain legacy Phase artifacts as history, but
those artifacts must not be mistaken for the current Evidence Gate.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


LEGACY_PHASE_RE = re.compile(r"Phase\s+[0-9]+(?:\.[0-9]+)?")
EXECUTOR_SET_RE = re.compile(r"checkpoint not in \{([^}]+)\}")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def audit(root: Path) -> dict[str, Any]:
    checkpoints = root / "CHECKPOINTS.md"
    runner = root / "scripts" / "progression_runner.py"
    contracts = root / "contracts" / "level-contracts.yaml"
    promotion = root / "scripts" / "promotion_gate.py"
    decision_log = root / "docs" / "decision-log.md"
    architecture_doc = root / "docs" / "current-evaluation-architecture.md"
    shadow_approval = root / "migration" / "shadow-validation-approval.json"

    checkpoint_text = read_text(checkpoints)
    runner_text = read_text(runner)
    decision_text = read_text(decision_log) + read_text(architecture_doc)
    shadow_text = read_text(shadow_approval)

    executor_match = EXECUTOR_SET_RE.search(runner_text)
    executor_ids = []
    if executor_match:
        executor_ids = sorted(re.findall(r"\"([0-9]+\.[0-9]+)\"", executor_match.group(1)))

    legacy_phase_active = bool(checkpoint_text and LEGACY_PHASE_RE.search(checkpoint_text))
    evidence_gate_present = contracts.exists() and promotion.exists()
    decision_separation_present = (
        "do not connect it to Level promotion" in decision_text
        or "Phase進捗とOperational Levelが分離" in decision_text
        or "historical development checkpoints from current capability evidence" in decision_text
        or "must not be used as a direct" in decision_text
    )

    blockers: list[str] = []
    if runner.exists() and executor_ids:
        blockers.append("legacy_progression_runner_registered")
    if not evidence_gate_present:
        blockers.append("evidence_gate_runtime_missing")
    if not decision_separation_present:
        blockers.append("phase_level_separation_not_recorded")

    shadow_approved = False
    if shadow_text:
        try:
            shadow_record = json.loads(shadow_text)
        except json.JSONDecodeError:
            shadow_record = {}
        shadow_approved = (
            shadow_record.get("status") == "passed"
            and shadow_record.get("approval") == "explicit"
        )

    if blockers:
        migration_status = "blocked"
    elif not shadow_approved:
        migration_status = "shadow_pending"
    else:
        migration_status = "ready_for_review"

    return {
        "schema_version": 1,
        "repository": str(root),
        "legacy": {
            "checkpoints_present": checkpoints.exists(),
            "phase_labels_present": legacy_phase_active,
            "progression_runner_present": runner.exists(),
            "registered_executor_ids": executor_ids,
        },
        "current_evidence_gate": {
            "contracts_present": contracts.exists(),
            "promotion_gate_present": promotion.exists(),
            "decision_separation_recorded": decision_separation_present,
        },
        "shadow_validation": {
            "approval_file_present": shadow_approval.exists(),
            "explicit_approval_recorded": shadow_approved,
        },
        "migration_status": migration_status,
        "blockers": blockers,
        "runtime_cutover_ready_for_review": migration_status == "ready_for_review",
        "cron_cutover_allowed": False,
        "decision": (
            "Keep legacy artifacts historical and resolve the listed migration blockers."
            if blockers
            else "Run and review shadow validation before any cron cutover."
            if not shadow_approved
            else "Evidence Gate runtime is present; cron cutover still requires the separately approved scheduler change."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit legacy Phase versus Evidence Gate boundaries")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = audit(args.root.resolve())
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["migration_status"] == "ready_for_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
