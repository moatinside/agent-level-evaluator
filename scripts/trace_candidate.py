#!/usr/bin/env python3
"""Convert one session trace into a sanitized, approval-gated eval candidate.

The output contains hashes and bounded structural metadata only. It does not
persist prompts, trace excerpts, tool arguments, session identifiers, or raw
outcomes. Candidates are never scoreable until a human approves them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password)=\S+")
URL_CRED_RE = re.compile(r"(?i)https?://[^\s/@:]+:[^\s/@]+@")
HOME_RE = re.compile(r"(?:/Users/[^\s]+|/home/[^\s]+|[A-Za-z]:\\[^\s]+)")


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def ref(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def sanitize_text(value: Any) -> str:
    if not isinstance(value, str):
        return "[REDACTED]"
    value = URL_CRED_RE.sub("https://[REDACTED]@", value)
    value = SECRET_RE.sub(lambda m: m.group(1) + "=[REDACTED]", value)
    return HOME_RE.sub("[LOCAL_PATH]", value)


def build_candidate(trace: Any) -> dict[str, Any]:
    if not isinstance(trace, dict):
        raise ValueError("trace must be an object")
    prompt = trace.get("prompt")
    outcome = trace.get("outcome")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("trace.prompt must be a non-empty string")
    if outcome is None:
        raise ValueError("trace.outcome is required")
    tools = trace.get("tool_calls", [])
    if not isinstance(tools, list) or not all(isinstance(item, str) for item in tools):
        raise ValueError("trace.tool_calls must be an array of tool names")
    criteria = trace.get("criteria", [])
    if not isinstance(criteria, list) or not all(isinstance(item, str) and item for item in criteria):
        raise ValueError("trace.criteria must be an array of non-empty strings")
    sanitized_trace = {
        "prompt": sanitize_text(prompt),
        "tool_calls": tools,
        "outcome": sanitize_text(outcome),
    }
    source_hash = hashlib.sha256(canonical(sanitized_trace)).hexdigest()
    return {
        "schema_version": 1,
        "candidate_id": "candidate:" + hashlib.sha256(canonical({"source": source_hash, "criteria": criteria})).hexdigest(),
        "status": "candidate",
        "source_ref": "trace:sha256:" + source_hash,
        "prompt_ref": ref(sanitize_text(prompt)),
        "outcome_ref": ref(sanitize_text(outcome)),
        "sanitized": True,
        "requires_human_approval": True,
        "criteria": criteria,
        "allowed_tools": sorted(set(tools)),
        "approved_by": None,
        "decision_reason": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        trace = json.loads(args.input.read_text(encoding="utf-8"))
        candidate = build_candidate(trace)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", "candidate_id": candidate["candidate_id"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
