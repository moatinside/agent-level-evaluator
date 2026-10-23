"""Structural and cross-field validation for the proposed Runtime Evidence V2 envelope.

This module is deliberately offline and dependency-free. It never logs input values.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "runtime-evidence-envelope-v2.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
MAX_EVENT_REF_BYTES = SCHEMA["properties"]["event_ref"]["maxLength"]
MAX_PAYLOAD_HASH_BYTES = SCHEMA["properties"]["payload_hash"]["maxLength"]
MAX_RECORD_HASH_BYTES = len("sha256:" + "0" * 64)
MAX_ENVELOPE_BYTES = 8192
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_UTC_TIMESTAMP = re.compile(SCHEMA["properties"]["observed_at"]["pattern"])


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def seal_event(event: dict[str, Any]) -> dict[str, Any]:
    """Hash a bounded canonical envelope, raising a value-free error on invalid input."""
    sealed = dict(event)
    sealed.pop("payload_hash", None)
    encoded, serialization_error = _bounded_canonical_json(sealed)
    if serialization_error is not None:
        raise ValueError(serialization_error)
    assert encoded is not None
    sealed["payload_hash"] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    _, serialization_error = _bounded_canonical_json(sealed)
    if serialization_error is not None:
        raise ValueError(serialization_error)
    return sealed


def _matches_type(value: Any, expected: str | list[str]) -> bool:
    choices = expected if isinstance(expected, list) else [expected]
    for choice in choices:
        if choice == "object" and isinstance(value, dict):
            return True
        if choice == "string" and isinstance(value, str):
            return True
        if choice == "integer" and type(value) is int:
            return True
        if choice == "number" and type(value) in (int, float):
            return True
        if choice == "boolean" and type(value) is bool:
            return True
        if choice == "null" and value is None:
            return True
        if choice == "array" and isinstance(value, list):
            return True
    return False


def _is_utc_timestamp(value: str) -> bool:
    if _UTC_TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _validate_node(value: Any, schema: dict[str, Any], errors: set[str]) -> None:
    expected_type = schema.get("type")
    if expected_type is not None and not _matches_type(value, expected_type):
        errors.add("wrong_type")
        return

    if "const" in schema and value != schema["const"]:
        errors.add("invalid_value")
    if "enum" in schema and value not in schema["enum"]:
        errors.add("invalid_value")

    if isinstance(value, str):
        if len(value) > schema.get("maxLength", len(value)):
            errors.add("limit_exceeded")
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            errors.add("invalid_format")
        if schema.get("format") == "date-time" and not _is_utc_timestamp(value):
            errors.add("invalid_timestamp")

    if type(value) is int:
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            errors.add("limit_exceeded")

    if isinstance(value, dict):
        required = schema.get("required", [])
        if any(key not in value for key in required):
            errors.add("missing_required")
        properties = schema.get("properties", {})
        for key, child in value.items():
            child_schema = properties.get(key)
            if child_schema is None:
                if schema.get("additionalProperties", True) is False:
                    errors.add("unknown_field")
                continue
            _validate_node(child, child_schema, errors)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not _is_utc_timestamp(value):
        return None
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _minimum_json_size(value: Any) -> int:
    """Return a safe lower bound without recursively traversing the input."""
    total = 0
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            total += len(item) + 2  # quotes plus at least one UTF-8 byte per code point
        elif isinstance(item, dict):
            count = len(item)
            minimum = 2 + max(0, count - 1) + 4 * count
            if total + minimum > MAX_ENVELOPE_BYTES:
                return total + minimum
            total += 2 + max(0, count - 1)  # braces and commas
            for key, child in item.items():
                if not isinstance(key, str):
                    raise TypeError("JSON object keys must be strings")
                total += len(key) + 3  # quoted key and colon
                pending.append(child)
        elif isinstance(item, (list, tuple)):
            count = len(item)
            minimum = 2 + max(0, count - 1) + count
            if total + minimum > MAX_ENVELOPE_BYTES:
                return total + minimum
            total += 2 + max(0, count - 1)  # brackets and commas
            pending.extend(item)
        else:
            total += 1  # every JSON scalar uses at least one byte
        if total > MAX_ENVELOPE_BYTES:
            return total
    return total


def _bounded_canonical_json(value: Any) -> tuple[bytes | None, str | None]:
    """Canonicalize under the byte ceiling, without building an oversized JSON string."""
    try:
        if _minimum_json_size(value) > MAX_ENVELOPE_BYTES:
            return None, "event_too_large"
        encoder = json.JSONEncoder(
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        chunks: list[bytes] = []
        total = 0
        for chunk in encoder.iterencode(value):
            encoded = chunk.encode("utf-8")
            total += len(encoded)
            if total > MAX_ENVELOPE_BYTES:
                return None, "event_too_large"
            chunks.append(encoded)
        return b"".join(chunks), None
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        return None, "not_json_value"


def validate_event(event: Any) -> tuple[str, ...]:
    """Return stable, value-free error codes; an empty tuple means valid V2 structure."""
    encoded, serialization_error = _bounded_canonical_json(event)
    if serialization_error is not None:
        return (serialization_error,)
    assert encoded is not None

    errors: set[str] = set()
    _validate_node(event, SCHEMA, errors)
    if not isinstance(event, dict):
        return tuple(sorted(errors))

    supplied_hash = event.get("payload_hash")
    if isinstance(supplied_hash, str) and _SHA256.fullmatch(supplied_hash):
        payload = dict(event)
        payload.pop("payload_hash", None)
        expected_hash = "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()
        if supplied_hash != expected_hash:
            errors.add("payload_hash_mismatch")

    provenance = event.get("provenance")
    execution = event.get("execution")
    assessment = event.get("assessment")
    if isinstance(provenance, dict) and isinstance(execution, dict) and isinstance(assessment, dict):
        persistence = execution.get("persistence_status")
        receipt = execution.get("persistence_receipt_ref")
        ordinary_scope = (
            provenance.get("source_class") == "ordinary_runtime"
            and provenance.get("task_class") == "ordinary_task"
            and provenance.get("classification_basis") == "gateway_dispatch"
            and isinstance(provenance.get("scope_ref"), str)
        )
        confirmed_receipt_claim = persistence == "confirmed" and isinstance(receipt, str)
        expected_eligibility = (
            "transport_only" if ordinary_scope and confirmed_receipt_claim else "excluded"
        )
        if assessment.get("evaluation_eligibility") != expected_eligibility:
            errors.add("eligibility_mismatch")

        if persistence == "confirmed" and not isinstance(receipt, str):
            errors.add("persistence_receipt_required")
        if persistence != "confirmed" and receipt is not None:
            errors.add("persistence_receipt_unexpected")

        started = _timestamp(execution.get("started_at"))
        ended = _timestamp(execution.get("ended_at"))
        if started is not None and ended is not None and started > ended:
            errors.add("timestamp_order_invalid")

    return tuple(sorted(errors))


def structural_disposition(event: Any) -> str:
    """Return a structural disposition only; no provenance, receipt, or HMAC is authenticated."""
    if validate_event(event):
        return "rejected"
    eligibility = event["assessment"]["evaluation_eligibility"]
    return (
        "structurally_transport_only"
        if eligibility == "transport_only"
        else "structurally_excluded"
    )
