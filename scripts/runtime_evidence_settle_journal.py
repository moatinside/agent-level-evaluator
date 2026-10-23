"""Offline reader for an explicitly supplied R2 settle-marker snapshot (JSONL).

The snapshot is produced by the Hermes exporter (``gateway/runtime_evidence_r2_export.py``)
under its own Class A/B budget; this module performs no network access. Each line must
be a closed, hash-bound settle marker. Any invalid line, oversize file, or conflicting
duplicate fails closed so the report never turns an unreadable journal into a count.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

SETTLE_MARKER_SCHEMA = "agent-level/runtime-evidence/settle-marker/v1"
MAX_SNAPSHOT_MARKERS = 100_000
MAX_LINE_BYTES = 1024
OUTBOX_OUTCOMES = ("persisted", "duplicate", "conflict", "outbox_unavailable", "outbox_failed")
_TERMINAL = {"completed", "failed", "interrupted", "skipped", "unknown"}
_KEYS = {"schema", "event_ref", "settled_at", "terminal_status", "outbox_outcome", "marker_hash"}
_HMAC_REF = re.compile(r"^hmac-sha256:v[1-9][0-9]*:[a-f0-9]{64}$")
_UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")


class SettleJournalError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def validate_settle_marker(marker: Any) -> tuple[str, ...]:
    """Mirror of the Hermes settle-marker contract; value-free error codes."""
    if not isinstance(marker, dict) or set(marker) != _KEYS:
        return ("marker_keys",)
    errors = set()
    if marker["schema"] != SETTLE_MARKER_SCHEMA:
        errors.add("marker_schema")
    if not isinstance(marker["event_ref"], str) or not _HMAC_REF.fullmatch(marker["event_ref"]):
        errors.add("marker_event_ref")
    if not isinstance(marker["settled_at"], str) or not _UTC.fullmatch(marker["settled_at"]):
        errors.add("marker_settled_at")
    if marker["terminal_status"] not in _TERMINAL:
        errors.add("marker_terminal_status")
    if marker["outbox_outcome"] not in OUTBOX_OUTCOMES:
        errors.add("marker_outbox_outcome")
    if not isinstance(marker["marker_hash"], str) or not _SHA256.fullmatch(marker["marker_hash"]):
        errors.add("marker_hash")
    if not errors:
        body = {k: v for k, v in marker.items() if k != "marker_hash"}
        if marker["marker_hash"] != "sha256:" + hashlib.sha256(_canonical(body)).hexdigest():
            errors.add("marker_hash_mismatch")
    return tuple(sorted(errors))


def load_settle_journal_snapshot(path: str | Path) -> dict[str, dict[str, Any]]:
    """Return ``{event_ref: marker}``; fail closed on any invalid or conflicting line."""
    snapshot = Path(path)
    if not snapshot.is_absolute():
        raise SettleJournalError("journal_snapshot_path_invalid")
    try:
        size = os.stat(snapshot).st_size
    except OSError:
        raise SettleJournalError("journal_snapshot_unavailable") from None
    if size > MAX_SNAPSHOT_MARKERS * (MAX_LINE_BYTES + 1):
        raise SettleJournalError("journal_snapshot_too_large")
    markers: dict[str, dict[str, Any]] = {}
    try:
        with open(snapshot, "rb") as handle:
            for line in handle:
                if len(line) > MAX_LINE_BYTES + 1:
                    raise SettleJournalError("journal_snapshot_line_invalid")
                if not line.strip():
                    continue
                try:
                    marker = json.loads(line.decode("utf-8"))
                except (UnicodeError, ValueError):
                    raise SettleJournalError("journal_snapshot_line_invalid") from None
                if validate_settle_marker(marker):
                    raise SettleJournalError("journal_snapshot_line_invalid")
                existing = markers.get(marker["event_ref"])
                if existing is not None and existing != marker:
                    raise SettleJournalError("journal_snapshot_conflict")
                markers[marker["event_ref"]] = marker
                if len(markers) > MAX_SNAPSHOT_MARKERS:
                    raise SettleJournalError("journal_snapshot_too_large")
    except OSError:
        raise SettleJournalError("journal_snapshot_unavailable") from None
    return markers


def reconcile(markers: dict[str, dict[str, Any]], outbox_refs: set[str]) -> dict[str, Any]:
    """Count-only reconciliation between the settle journal and validated Outbox rows."""
    journal_refs = set(markers)
    outcomes = {outcome: 0 for outcome in OUTBOX_OUTCOMES}
    for marker in markers.values():
        outcomes[marker["outbox_outcome"]] += 1
    return {
        "emitted_basis": "r2_settle_markers_lower_bound",
        "journal_settled": len(journal_refs),
        "journal_and_outbox": len(journal_refs & outbox_refs),
        "journal_only": len(journal_refs - outbox_refs),
        "outbox_only": len(outbox_refs - journal_refs),
        "journal_reported_outbox_outcomes": outcomes,
    }
