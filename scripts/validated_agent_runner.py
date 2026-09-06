#!/usr/bin/env python3
"""Buffered stdin/stdout runner for Level 5 response validation.

Input JSON:
{"draft": "...", "rules": {"required_patterns": [], "forbidden_patterns": []},
 "corrections": ["..."], "max_iterations": 3}

The runner only returns a validation result. It never delivers the response.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from response_validation import validate_buffered_response  # noqa: E402


def main() -> int:
    try:
        request = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"status": "inconclusive", "delivery_allowed": False, "reason": f"invalid input: {exc}"}, ensure_ascii=False))
        return 1
    if not isinstance(request, dict) or "draft" not in request:
        print(json.dumps({"status": "inconclusive", "delivery_allowed": False, "reason": "draft is required"}, ensure_ascii=False))
        return 1
    result = validate_buffered_response(
        request.get("draft"),
        request.get("rules", {}),
        corrections=request.get("corrections", []),
        max_iterations=request.get("max_iterations", 3),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
