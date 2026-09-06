#!/usr/bin/env python3
"""Run producer -> validator -> correction-agent -> revalidation without delivery.

The producer and correction commands are configured by the trusted evaluator
operator, never supplied by the task payload. Both commands communicate over
JSON stdin/stdout. This runner only returns a validated response; it never sends
anything to a user or platform.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from response_validation import STATUS_PASS, validate_text  # noqa: E402


def command_args(value: str) -> list[str]:
    args = shlex.split(value)
    if not args:
        raise ValueError("command must not be empty")
    return args


def invoke(command: list[str], payload: dict[str, Any], timeout: int) -> str:
    proc = subprocess.run(
        command,
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"command exited {proc.returncode}")
    return proc.stdout.strip()


def extract_producer_answer(output: str) -> str:
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        return output
    if isinstance(value, dict) and isinstance(value.get("answer"), str):
        return value["answer"]
    raise ValueError("producer must return text or JSON object with string answer")


def extract_correction(output: str) -> str:
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        return output
    if isinstance(value, dict) and isinstance(value.get("correction"), str):
        return value["correction"]
    raise ValueError("correction command must return text or JSON object with string correction")


def run(request: dict[str, Any], producer: list[str], correction: list[str] | None, timeout: int, max_iterations: int) -> dict[str, Any]:
    rules = request.get("rules", {})
    if not isinstance(rules, dict):
        return {"status": "inconclusive", "delivery_allowed": False, "final_response": None, "reason": "rules must be an object", "attempts": []}
    try:
        draft = extract_producer_answer(invoke(producer, request, timeout))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return {"status": "inconclusive", "delivery_allowed": False, "final_response": None, "reason": f"producer failed: {exc}", "attempts": []}

    attempts: list[dict[str, Any]] = []
    current = draft
    for iteration in range(max_iterations):
        validation = validate_text(
            current,
            required_patterns=rules.get("required_patterns", []),
            forbidden_patterns=rules.get("forbidden_patterns", []),
        )
        attempts.append({"iteration": iteration + 1, "validation": validation})
        if validation["status"] == STATUS_PASS:
            return {"status": STATUS_PASS, "delivery_allowed": True, "final_response": current, "attempts": attempts}
        if validation["status"] != "blocked":
            return {"status": "inconclusive", "delivery_allowed": False, "final_response": None, "reason": "validator could not determine a safe result", "attempts": attempts}
        if correction is None:
            return {"status": "blocked", "delivery_allowed": False, "final_response": None, "reason": "no correction agent configured", "attempts": attempts}
        correction_payload = {
            "request": request,
            "draft": current,
            "issues": validation["issues"],
            "iteration": iteration + 1,
        }
        try:
            current = extract_correction(invoke(correction, correction_payload, timeout))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return {"status": "inconclusive", "delivery_allowed": False, "final_response": None, "reason": f"correction agent failed: {exc}", "attempts": attempts}

    return {"status": "blocked", "delivery_allowed": False, "final_response": None, "reason": "maximum validation iterations reached", "attempts": attempts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--producer", required=True, help="trusted producer command")
    parser.add_argument("--correction", help="trusted correction-agent command")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--max-iterations", type=int, default=3)
    args = parser.parse_args()
    if args.timeout_seconds < 1 or args.max_iterations < 1:
        parser.error("timeout and max-iterations must be positive")
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        result = run(request, command_args(args.producer), command_args(args.correction) if args.correction else None, args.timeout_seconds, args.max_iterations)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        result = {"status": "inconclusive", "delivery_allowed": False, "final_response": None, "reason": f"invalid runner input: {exc}", "attempts": []}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == STATUS_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
