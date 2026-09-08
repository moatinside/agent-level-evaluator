#!/usr/bin/env python3
"""Compare legacy observations with the read-only current evaluator.

The command is intentionally side-effect free: it reads existing legacy state,
invokes the current read-only evaluator, and writes only the requested report.
It never runs a legacy Phase executor and never creates cutover approval.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


def load_current_evaluator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "evaluate_current_state", SCRIPT_DIR / "evaluate_current_state.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load evaluate_current_state.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evaluate_current_state = load_current_evaluator()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def run_shadow(legacy_root: Path, current_root: Path) -> dict[str, Any]:
    legacy_root = legacy_root.resolve()
    current_root = current_root.resolve()
    legacy_state = load_json(legacy_root / "execution-evidence" / "2.3" / "state.json")
    current = evaluate_current_state.evaluate(current_root)

    checks = {
        "legacy_observation_available": bool(legacy_state),
        "current_entrypoint_read_only": current["legacy_phase_execution"]["executed"] is False,
        "promotion_not_granted": current["promotion"]["status"] == "not_promoted",
        "cron_cutover_state_explicit": isinstance(current["cron_cutover_allowed"], bool),
    }
    return {
        "schema_version": 1,
        "mode": "migration_shadow",
        "status": "passed" if all(checks.values()) else "failed",
        "approval": "pending",
        "legacy_root": str(legacy_root),
        "current_root": str(current_root),
        "checks": checks,
        "legacy_observation": {
            "status": legacy_state.get("status", "missing"),
            "elapsed_days": legacy_state.get("elapsed_days"),
            "novel_results": legacy_state.get("novel_results"),
        },
        "current_observation": {
            "migration_status": current["migration_status"],
            "operational_level": current["evidence"]["operational_level"],
            "functional_ceiling": current["evidence"]["functional_ceiling"],
            "promotion_status": current["promotion"]["status"],
        },
        "side_effects": {
            "legacy_executor_invoked": False,
            "checkpoint_mutated": False,
            "promotion_granted": False,
            "cron_configuration_changed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a side-effect-free migration shadow comparison")
    parser.add_argument("--legacy-root", type=Path, required=True)
    parser.add_argument("--current-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = run_shadow(args.legacy_root, args.current_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "approval": result["approval"], "output": str(args.output)}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
