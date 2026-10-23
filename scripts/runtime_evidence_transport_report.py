"""Value-free report over explicitly supplied V2 Outbox and ledger databases.

Counts are transport observations only. No path, event identifier, hash, conversation
content, level, or promotion verdict is emitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterator

from scripts.runtime_evidence_consumer import (
    ConsumerError,
    LEDGER_DB_VERSION,
    _SINK_ID,
    _connect_readonly,
    _decode_envelope,
    _validate_ledger_schema,
    _validate_outbox_schema,
    _validate_receipt,
    _RECEIPT_MAX_BYTES,
)
from scripts.runtime_evidence_contract import (
    MAX_ENVELOPE_BYTES,
    MAX_EVENT_REF_BYTES,
    MAX_PAYLOAD_HASH_BYTES,
    MAX_RECORD_HASH_BYTES,
    structural_disposition,
)
from scripts.runtime_evidence_settle_journal import (
    SettleJournalError,
    load_settle_journal_snapshot,
    reconcile,
)

REPORT_SCHEMA_VERSION = 2
MAX_REPORT_RECORDS = 100_000


class RuntimeEvidenceReportError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _iter_rows(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    params: tuple[Any, ...] = (),
) -> Iterator[sqlite3.Row | tuple]:
    try:
        cursor = conn.execute(query, (*params, limit + 1))
        for count, row in enumerate(cursor, start=1):
            if count > limit:
                raise RuntimeEvidenceReportError("report_record_limit_exceeded")
            yield row
    except RuntimeEvidenceReportError:
        raise
    except sqlite3.Error:
        raise RuntimeEvidenceReportError("report_source_unavailable") from None


def _count(
    conn: sqlite3.Connection,
    query: str,
    params: tuple[Any, ...] = (),
) -> int:
    try:
        return int(conn.execute(query, params).fetchone()[0])
    except (sqlite3.Error, TypeError, ValueError, IndexError):
        raise RuntimeEvidenceReportError("report_source_unavailable") from None


def build_runtime_evidence_transport_report(
    outbox_db_path: str | Path,
    ledger_db_path: str | Path,
    *,
    sink_id: str,
    max_records: int,
    journal_markers: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a bounded transport-only report; callers must choose both DB paths.

    ``emitted`` stays null unless an explicitly loaded R2 settle-journal snapshot is
    passed (see ``scripts/runtime_evidence_settle_journal.py``); it is then a lower
    bound with a separate journal/Outbox reconciliation section.
    """
    outbox_path = Path(outbox_db_path)
    ledger_path = Path(ledger_db_path)
    if not outbox_path.is_absolute() or not ledger_path.is_absolute():
        raise RuntimeEvidenceReportError("database_path_invalid")
    if os.path.abspath(outbox_path) == os.path.abspath(ledger_path):
        raise RuntimeEvidenceReportError("database_paths_must_differ")
    if not isinstance(sink_id, str) or _SINK_ID.fullmatch(sink_id) is None:
        raise RuntimeEvidenceReportError("sink_id_invalid")
    if type(max_records) is not int or not 1 <= max_records <= MAX_REPORT_RECORDS:
        raise RuntimeEvidenceReportError("report_record_limit_invalid")

    anomalies = {
        "invalid_outbox_rows": 0,
        "invalid_ledger_rows": 0,
        "outbox_ledger_mismatches": 0,
        "invalid_receipts": 0,
        "receipts_without_exact_ledger_row": 0,
        "receipts_without_exact_outbox_row": 0,
    }
    outbox_by_ref: dict[str, tuple[str, int, bytes]] = {}
    ledger_by_ref: dict[str, tuple[str, int, bytes, str]] = {}
    outbox_persisted = 0
    ledger_persisted = 0
    outbox_conflicts = 0
    ledger_conflicts = 0
    transport_only = 0
    structurally_excluded = 0
    acknowledged = 0

    try:
        with closing(_connect_readonly(outbox_path)) as conn:
            if int(conn.execute("PRAGMA user_version").fetchone()[0]) != 1:
                raise RuntimeEvidenceReportError("outbox_schema_unsupported")
            _validate_outbox_schema(conn)
            oversized_metadata = _count(
                conn,
                "SELECT COUNT(*) FROM outbox_events "
                "WHERE length(CAST(event_ref AS BLOB)) > ? "
                "OR length(CAST(payload_hash AS BLOB)) > ?",
                (MAX_EVENT_REF_BYTES, MAX_PAYLOAD_HASH_BYTES),
            )
            if oversized_metadata:
                raise RuntimeEvidenceReportError("report_record_size_exceeded")
            oversized_envelopes = _count(
                conn,
                "SELECT COUNT(*) FROM outbox_events "
                "WHERE length(CAST(envelope_json AS BLOB)) > ?",
                (MAX_ENVELOPE_BYTES,),
            )
            if oversized_envelopes:
                raise RuntimeEvidenceReportError("report_record_size_exceeded")
            for row in _iter_rows(
                conn,
                "SELECT event_ref, payload_hash, schema_version, envelope_json "
                "FROM outbox_events ORDER BY seq LIMIT ?",
                max_records,
            ):
                outbox_persisted += 1
                try:
                    event_ref, payload_hash, schema_version, envelope_json = row
                    raw_envelope = bytes(envelope_json)
                    event, canonical = _decode_envelope(raw_envelope)
                    if (
                        event_ref != event["event_ref"]
                        or payload_hash != event["payload_hash"]
                        or schema_version != event["schema_version"]
                        or canonical != raw_envelope
                    ):
                        raise ValueError
                    outbox_by_ref[event_ref] = (
                        payload_hash,
                        schema_version,
                        hashlib.sha256(canonical).digest(),
                    )
                except (ConsumerError, KeyError, TypeError, ValueError, OverflowError):
                    anomalies["invalid_outbox_rows"] += 1
            outbox_conflicts = _count(conn, "SELECT COUNT(*) FROM outbox_conflicts")

        with closing(_connect_readonly(ledger_path)) as conn:
            if int(conn.execute("PRAGMA user_version").fetchone()[0]) != LEDGER_DB_VERSION:
                raise RuntimeEvidenceReportError("ledger_schema_unsupported")
            _validate_ledger_schema(conn)
            oversized_metadata = _count(
                conn,
                "SELECT COUNT(*) FROM runtime_events "
                "WHERE length(CAST(event_ref AS BLOB)) > ? "
                "OR length(CAST(payload_hash AS BLOB)) > ? "
                "OR length(CAST(record_hash AS BLOB)) > ?",
                (MAX_EVENT_REF_BYTES, MAX_PAYLOAD_HASH_BYTES, MAX_RECORD_HASH_BYTES),
            )
            oversized_receipt_metadata = _count(
                conn,
                "SELECT COUNT(*) FROM transport_receipts WHERE sink_id=? AND ("
                "length(CAST(event_ref AS BLOB)) > ? "
                "OR length(CAST(payload_hash AS BLOB)) > ?)",
                (sink_id, MAX_EVENT_REF_BYTES, MAX_PAYLOAD_HASH_BYTES),
            )
            oversized_envelopes = _count(
                conn,
                "SELECT COUNT(*) FROM runtime_events "
                "WHERE length(CAST(envelope_json AS BLOB)) > ?",
                (MAX_ENVELOPE_BYTES,),
            )
            oversized_receipts = _count(
                conn,
                "SELECT COUNT(*) FROM transport_receipts "
                "WHERE sink_id=? AND length(CAST(receipt_json AS BLOB)) > ?",
                (sink_id, _RECEIPT_MAX_BYTES),
            )
            if oversized_metadata or oversized_receipt_metadata or oversized_envelopes or oversized_receipts:
                raise RuntimeEvidenceReportError("report_record_size_exceeded")
            for row in _iter_rows(
                conn,
                "SELECT event_ref, payload_hash, schema_version, envelope_json, record_hash "
                "FROM runtime_events ORDER BY event_ref LIMIT ?",
                max_records,
            ):
                ledger_persisted += 1
                try:
                    event_ref, payload_hash, schema_version, envelope_json, record_hash = row
                    raw_envelope = bytes(envelope_json)
                    event, canonical = _decode_envelope(raw_envelope)
                    expected_record_hash = "sha256:" + hashlib.sha256(canonical).hexdigest()
                    if (
                        event_ref != event["event_ref"]
                        or payload_hash != event["payload_hash"]
                        or schema_version != event["schema_version"]
                        or canonical != raw_envelope
                        or record_hash != expected_record_hash
                    ):
                        raise ValueError
                    ledger_by_ref[event_ref] = (
                        payload_hash,
                        schema_version,
                        hashlib.sha256(canonical).digest(),
                        record_hash,
                    )
                    disposition = structural_disposition(event)
                    if disposition == "structurally_transport_only":
                        transport_only += 1
                    elif disposition == "structurally_excluded":
                        structurally_excluded += 1
                    else:
                        anomalies["invalid_ledger_rows"] += 1
                except (ConsumerError, KeyError, TypeError, ValueError, OverflowError):
                    anomalies["invalid_ledger_rows"] += 1
            ledger_conflicts = _count(conn, "SELECT COUNT(*) FROM runtime_event_conflicts")
            for row in _iter_rows(
                conn,
                "SELECT event_ref, payload_hash, schema_version, sink_id, receipt_json "
                "FROM transport_receipts WHERE sink_id=? ORDER BY event_ref LIMIT ?",
                max_records,
                (sink_id,),
            ):
                try:
                    event_ref, payload_hash, schema_version, row_sink_id, receipt_json = row
                    receipt_bytes = bytes(receipt_json)
                    receipt = json.loads(receipt_bytes.decode("utf-8"))
                    if (
                        not _validate_receipt(receipt)
                        or receipt.get("event_ref") != event_ref
                        or receipt.get("payload_hash") != payload_hash
                        or receipt.get("event_schema_version") != schema_version
                        or receipt.get("sink_id") != row_sink_id
                        or row_sink_id != sink_id
                        or receipt.get("readback_status") != "exact_match"
                    ):
                        anomalies["invalid_receipts"] += 1
                        continue
                except (
                    UnicodeError,
                    json.JSONDecodeError,
                    ConsumerError,
                    KeyError,
                    TypeError,
                    ValueError,
                    OverflowError,
                ):
                    anomalies["invalid_receipts"] += 1
                    continue

                ledger_value = ledger_by_ref.get(event_ref)
                if ledger_value is None or ledger_value[:2] != (payload_hash, schema_version):
                    anomalies["receipts_without_exact_ledger_row"] += 1
                    continue
                outbox_value = outbox_by_ref.get(event_ref)
                exact_outbox = (
                    outbox_value is not None
                    and outbox_value == (payload_hash, schema_version, ledger_value[2])
                )
                if not exact_outbox:
                    anomalies["receipts_without_exact_outbox_row"] += 1
                    continue
                if receipt.get("ledger_record_hash") != ledger_value[3]:
                    anomalies["invalid_receipts"] += 1
                    continue
                acknowledged += 1
    except ConsumerError as exc:
        raise RuntimeEvidenceReportError(exc.code) from None
    except RuntimeEvidenceReportError:
        raise
    except (sqlite3.Error, OSError, ValueError):
        raise RuntimeEvidenceReportError("report_source_unavailable") from None

    exact_matches = 0
    for event_ref, outbox_value in outbox_by_ref.items():
        ledger_value = ledger_by_ref.get(event_ref)
        if ledger_value is None:
            continue
        if outbox_value == ledger_value[:3]:
            exact_matches += 1
        else:
            anomalies["outbox_ledger_mismatches"] += 1

    pending = 0
    for event_ref, outbox_value in outbox_by_ref.items():
        ledger_value = ledger_by_ref.get(event_ref)
        if ledger_value is None or ledger_value[:3] != outbox_value:
            pending += 1
    orphaned = sum(1 for event_ref in ledger_by_ref if event_ref not in outbox_by_ref)
    report_status = "incomplete" if any(anomalies.values()) else "partial"

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "report_status": report_status,
        "sink_id": sink_id,
        "counts": {
            "emitted": None,
            "outbox_persisted": outbox_persisted,
            "outbox_validated": len(outbox_by_ref),
            "outbox_conflicts": outbox_conflicts,
            "ledger_persisted": ledger_persisted,
            "ledger_conflicts": ledger_conflicts,
            "consumer_acknowledged": acknowledged,
            "outbox_to_ledger_exact": exact_matches,
            "report_visible": len(ledger_by_ref),
            "outbox_pending_without_ledger": pending,
            "ledger_orphan_without_outbox": orphaned,
            "structurally_transport_only": transport_only,
            "structurally_excluded": structurally_excluded,
            "measurement_complete": None,
            "evaluation_eligible": None,
        },
        "outcome_counts": {
            "accepted": acknowledged,
            "rejected": {
                "invalid_outbox_rows": anomalies["invalid_outbox_rows"],
                "invalid_ledger_rows": anomalies["invalid_ledger_rows"],
                "invalid_receipts": anomalies["invalid_receipts"],
            },
            "duplicate": None,
            "conflict": {
                "outbox_conflict_rows": outbox_conflicts,
                "ledger_conflict_rows": ledger_conflicts,
            },
        },
        "unavailable_count_reasons": {
            "emitted": "independent_capture_denominator_not_implemented",
            "measurement_complete": "semantic_measurement_not_implemented",
            "evaluation_eligible": "eligibility_decision_not_implemented",
            "duplicate": "duplicate_occurrence_not_durably_recorded",
        },
        "anomaly_counts": anomalies,
        "claims": {
            "provenance_authenticated": False,
            "semantic_capability_assessed": False,
            "promotion_input": False,
            "legacy_evidence_included": False,
        },
    }
    if journal_markers is not None:
        reconciliation = reconcile(journal_markers, set(outbox_by_ref))
        report["counts"]["emitted"] = reconciliation["journal_settled"]
        del report["unavailable_count_reasons"]["emitted"]
        report["capture_reconciliation"] = reconciliation
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outbox-db", required=True)
    parser.add_argument("--ledger-db", required=True)
    parser.add_argument("--sink-id", required=True)
    parser.add_argument("--max-records", required=True, type=int)
    parser.add_argument("--journal-snapshot", help="absolute path to an exported R2 settle-marker JSONL")
    args = parser.parse_args(argv)
    try:
        journal_markers = (
            load_settle_journal_snapshot(args.journal_snapshot) if args.journal_snapshot else None
        )
        report = build_runtime_evidence_transport_report(
            args.outbox_db,
            args.ledger_db,
            sink_id=args.sink_id,
            max_records=args.max_records,
            journal_markers=journal_markers,
        )
    except (ConsumerError, RuntimeEvidenceReportError, SettleJournalError) as exc:
        print(json.dumps({"status": "error", "error_code": exc.code}, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
