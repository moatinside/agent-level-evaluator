#!/usr/bin/env python3
"""Run trusted producer/correction commands over a shadow case batch.

Case files contain only named scenarios and validation rules. Executable
commands are supplied by the operator, not by the case payload. The batch
runner appends one metadata-first Evidence record per case and prints aggregate
counts without response text.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_operational_evidence import append_record, collect  # noqa: E402


HASH_RE = "sha256:"


def timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def command(value: str) -> list[str]:
    args = shlex.split(value)
    if not args:
        raise ValueError("trusted command must not be empty")
    return args


def execute_case(case: dict[str, Any], producer_commands: dict[str, list[str]], correction: list[str] | None, timeout: int, max_iterations: int) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id = case.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id must be a non-empty string")
    producer_name = case.get("producer")
    if producer_name not in producer_commands:
        raise ValueError(f"unknown trusted producer: {producer_name}")
    request = {"input": case.get("input", "shadow-case"), "rules": case.get("rules", {})}
    cmd = [sys.executable, str(Path(__file__).resolve().parent / "validated_command_runner.py"), "--producer", " ".join(shlex.quote(x) for x in producer_commands[producer_name]), "--timeout-seconds", str(timeout), "--max-iterations", str(max_iterations)]
    if case.get("correction", False):
        if correction is None:
            raise ValueError("case requests correction but no correction command was configured")
        cmd += ["--correction", " ".join(shlex.quote(x) for x in correction)]
    proc = subprocess.run(cmd, input=json.dumps(request, ensure_ascii=False), text=True, capture_output=True, timeout=timeout + 5)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"validated runner returned invalid JSON for {case_id}") from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"validated runner returned non-object for {case_id}")
    return request, result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--producer-good", required=True)
    parser.add_argument("--producer-bad", required=True)
    parser.add_argument("--correction")
    parser.add_argument("--agent-configuration-id", required=True)
    parser.add_argument("--evaluator-configuration-id", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--max-iterations", type=int, default=3)
    args = parser.parse_args()
    if args.timeout_seconds < 1 or args.max_iterations < 1:
        parser.error("timeout and max-iterations must be positive")
    try:
        cases = json.loads(args.cases.read_text(encoding="utf-8"))
        if not isinstance(cases, list) or not cases:
            raise ValueError("cases must be a non-empty JSON array")
        producers = {"good": command(args.producer_good), "bad": command(args.producer_bad)}
        correction = command(args.correction) if args.correction else None
        counts = {"total": 0, "passed": 0, "blocked": 0, "inconclusive": 0, "failed": 0, "correction_runs": 0, "safe_stops": 0}
        for index, case in enumerate(cases, start=1):
            if not isinstance(case, dict):
                raise ValueError(f"case {index} must be an object")
            request, result = execute_case(case, producers, correction, args.timeout_seconds, args.max_iterations)
            started = timestamp()
            ended = timestamp()
            metadata = {
                "run_id": f"shadow-{index:04d}-{case.get('case_id', 'unknown')}",
                "level": 5,
                "capability_id": "self_reflection",
                "capability_contract_version": "1.0.0",
                "agent_configuration_id": args.agent_configuration_id,
                "evaluator_configuration_id": args.evaluator_configuration_id,
                "scenario_id": str(case.get("case_id", f"case-{index}")),
                "trigger_origin": "harness",
                "environment_class": "shadow",
                "started_at": started,
                "ended_at": ended,
            }
            record = collect(request, result, metadata)
            append_record(args.output, record)
            status = record["result"]
            counts["total"] += 1
            counts[status] += 1
            counts["correction_runs"] += int(record["acceptance_results"]["correction_invoked"] > 0)
            counts["safe_stops"] += int(bool(record["negative_evidence"]))
        print(json.dumps({"status": "PASS", "counts": counts, "output": str(args.output)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
