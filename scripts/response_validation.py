#!/usr/bin/env python3
"""Deterministic buffered response validation for Level 5 evidence.

This module never sends a response. It validates a buffered candidate and either
returns a passing candidate or blocks delivery. Agent-generated corrections are
supplied by the caller; this module does not invent them.
"""
from __future__ import annotations

import re
from typing import Any


STATUS_PASS = "passed"
STATUS_BLOCKED = "blocked"
STATUS_INCONCLUSIVE = "inconclusive"


def validate_text(
    text: str,
    *,
    required_patterns: list[str] | None = None,
    forbidden_patterns: list[str] | None = None,
) -> dict[str, Any]:
    """Validate one buffered response against pre-registered regex rules."""
    if not isinstance(text, str):
        return {
            "status": STATUS_INCONCLUSIVE,
            "issues": [{"id": "text-type", "message": "candidate must be a string"}],
        }

    issues: list[dict[str, str]] = []
    for index, pattern in enumerate(required_patterns or []):
        try:
            matched = bool(re.search(pattern, text, re.S))
        except re.error as exc:
            issues.append({
                "id": f"required-pattern-invalid:{index}",
                "message": f"invalid required pattern: {exc}",
            })
            continue
        if not matched:
            issues.append({
                "id": f"required-pattern-missing:{index}",
                "pattern": pattern,
                "message": "required pattern is missing",
            })

    for index, pattern in enumerate(forbidden_patterns or []):
        try:
            matched = bool(re.search(pattern, text, re.S))
        except re.error as exc:
            issues.append({
                "id": f"forbidden-pattern-invalid:{index}",
                "message": f"invalid forbidden pattern: {exc}",
            })
            continue
        if matched:
            issues.append({
                "id": f"forbidden-pattern-present:{index}",
                "pattern": pattern,
                "message": "forbidden pattern is present",
            })

    invalid_rule = any("invalid" in issue["id"] for issue in issues)
    return {
        "status": STATUS_INCONCLUSIVE if invalid_rule else (STATUS_PASS if not issues else STATUS_BLOCKED),
        "issues": issues,
    }


def validate_buffered_response(
    draft: Any,
    rules: dict[str, Any],
    *,
    corrections: list[str] | None = None,
    max_iterations: int = 3,
) -> dict[str, Any]:
    """Run validation and caller-supplied correction candidates without delivery."""
    if not isinstance(max_iterations, int) or max_iterations < 1:
        return {
            "status": STATUS_INCONCLUSIVE,
            "final_response": None,
            "attempts": [],
            "reason": "max_iterations must be a positive integer",
        }
    if not isinstance(rules, dict):
        return {
            "status": STATUS_INCONCLUSIVE,
            "final_response": None,
            "attempts": [],
            "reason": "rules must be an object",
        }

    current = draft
    candidates = corrections or []
    attempts: list[dict[str, Any]] = []
    for iteration in range(max_iterations):
        result = validate_text(
            current,
            required_patterns=rules.get("required_patterns", []),
            forbidden_patterns=rules.get("forbidden_patterns", []),
        )
        attempts.append({"iteration": iteration + 1, "validation": result})
        if result["status"] == STATUS_PASS:
            return {
                "status": STATUS_PASS,
                "final_response": current,
                "attempts": attempts,
                "delivery_allowed": True,
            }
        if result["status"] == STATUS_INCONCLUSIVE:
            return {
                "status": STATUS_INCONCLUSIVE,
                "final_response": None,
                "attempts": attempts,
                "delivery_allowed": False,
                "reason": "validator could not determine a safe result",
            }
        correction_index = iteration
        if correction_index >= len(candidates):
            return {
                "status": STATUS_BLOCKED,
                "final_response": None,
                "attempts": attempts,
                "delivery_allowed": False,
                "reason": "no correction candidate supplied",
            }
        candidate = candidates[correction_index]
        if not isinstance(candidate, str):
            return {
                "status": STATUS_INCONCLUSIVE,
                "final_response": None,
                "attempts": attempts,
                "delivery_allowed": False,
                "reason": "correction candidate must be a string",
            }
        current = candidate

    return {
        "status": STATUS_BLOCKED,
        "final_response": None,
        "attempts": attempts,
        "delivery_allowed": False,
        "reason": "maximum validation iterations reached",
    }
