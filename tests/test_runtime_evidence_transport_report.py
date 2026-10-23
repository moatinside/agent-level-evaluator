from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import scripts.evidence_report as evidence_report
import scripts.runtime_evidence_transport_report as transport_report
from scripts.runtime_evidence_contract import (
    MAX_ENVELOPE_BYTES,
    MAX_EVENT_REF_BYTES,
    MAX_PAYLOAD_HASH_BYTES,
    MAX_RECORD_HASH_BYTES,
    seal_event,
)
from scripts.runtime_evidence_consumer import (
    RuntimeEvidenceConsumer,
    initialize_runtime_evidence_ledger,
)
from scripts.runtime_evidence_transport_report import (
    RuntimeEvidenceReportError,
    build_runtime_evidence_transport_report,
    main as report_main,
)


SINK_ID = "fixture-ledger"
ROOT = Path(__file__).resolve().parents[1]


class _CursorProxy:
    def __init__(self, cursor, query: str):
        self._cursor = cursor
        self._query = query

    def fetchall(self):
        if "envelope_json" in self._query or "receipt_json" in self._query:
            raise AssertionError("report must stream payload-bearing rows")
        return self._cursor.fetchall()

    def fetchone(self):
        return self._cursor.fetchone()

    def __iter__(self):
        return iter(self._cursor)


class _ConnectionProxy:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, query: str, params=()):
        return _CursorProxy(self._connection.execute(query, params), query)

    def close(self):
        self._connection.close()


def _event(event_ref_digit: str = "a", observed_at: str = "2026-10-20T12:00:00Z") -> dict:
    def ref(char: str) -> str:
        return "hmac-sha256:v1:" + char * 64

    def digest(char: str) -> str:
        return "sha256:" + char * 64
    body = {
        "schema_version": 2,
        "event_type": "turn_settled",
        "event_ref": ref(event_ref_digit),
        "observed_at": observed_at,
        "provenance": {
            "trigger_origin": "hermes_gateway",
            "source_class": "ordinary_runtime",
            "task_class": "ordinary_task",
            "classification_basis": "gateway_dispatch",
            "platform": "discord",
            "profile_ref": ref("b"),
            "session_ref": ref("c"),
            "episode_ref": ref("d"),
            "scope_ref": ref("e"),
        },
        "execution": {
            "execution_mode": "shadow",
            "terminal_status": "completed",
            "started_at": "2026-10-20T11:59:59Z",
            "ended_at": observed_at,
            "persistence_status": "confirmed",
            "persistence_receipt_ref": ref("f"),
            "delivery_status": "delivered",
            "runtime_build_id": digest("1"),
            "agent_configuration_id": None,
            "capture_configuration_id": None,
        },
        "trace": {
            "turn_count": 1,
            "tool_call_count": 2,
            "tool_error_count": 0,
            "correction_count": 0,
            "evidence_reference_count": 1,
            "iteration_count": 2,
        },
        "assessment": {
            "transport_status": "captured",
            "measurement_status": "not_assessed",
            "evaluation_eligibility": "transport_only",
        },
    }
    return seal_event(body)


def _create_outbox(path: Path, events: list[dict]) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE outbox_events ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, event_ref TEXT NOT NULL UNIQUE, "
            "payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, "
            "envelope_json BLOB NOT NULL, created_at TEXT NOT NULL);"
            "CREATE TABLE outbox_conflicts ("
            "conflict_id INTEGER PRIMARY KEY AUTOINCREMENT, event_ref TEXT NOT NULL, "
            "payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, "
            "candidate_sha256 TEXT NOT NULL, envelope_json BLOB NOT NULL, "
            "recorded_at TEXT NOT NULL, UNIQUE(event_ref, candidate_sha256));"
            "PRAGMA user_version=1;"
        )
        for index, event in enumerate(events):
            data = json.dumps(
                event, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            conn.execute(
                "INSERT INTO outbox_events "
                "(event_ref, payload_hash, schema_version, envelope_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (event["event_ref"], event["payload_hash"], 2, data, f"2026-10-20T12:00:0{index}Z"),
            )
    path.chmod(0o600)


class RuntimeEvidenceTransportReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.outbox = self.root / "outbox.sqlite3"
        self.ledger = self.root / "ledger.sqlite3"
        self.event = _event()
        _create_outbox(self.outbox, [self.event])
        initialize_runtime_evidence_ledger(self.ledger)
        self.consumer = RuntimeEvidenceConsumer(
            self.ledger,
            sink_id=SINK_ID,
            clock=lambda: datetime(2026, 10, 20, 12, 1, tzinfo=timezone.utc),
        )
        self.consumer.consume_outbox_event(self.outbox, seq=1)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_report_separates_observed_counts_from_unimplemented_denominators(self):
        outbox_hash = hashlib.sha256(self.outbox.read_bytes()).hexdigest()
        ledger_hash = hashlib.sha256(self.ledger.read_bytes()).hexdigest()
        report = build_runtime_evidence_transport_report(
            self.outbox, self.ledger, sink_id=SINK_ID, max_records=100
        )
        counts = report["counts"]
        self.assertEqual(report["report_status"], "partial")
        self.assertEqual(counts["outbox_persisted"], 1)
        self.assertEqual(counts["outbox_validated"], 1)
        self.assertEqual(counts["ledger_persisted"], 1)
        self.assertEqual(counts["consumer_acknowledged"], 1)
        self.assertEqual(counts["outbox_to_ledger_exact"], 1)
        self.assertEqual(counts["report_visible"], 1)
        self.assertIsNone(counts["emitted"])
        self.assertIsNone(counts["measurement_complete"])
        self.assertIsNone(counts["evaluation_eligible"])
        self.assertFalse(report["claims"]["promotion_input"])
        self.assertFalse(report["claims"]["provenance_authenticated"])
        self.assertEqual(report["report_schema_version"], 2)
        self.assertEqual(
            report["outcome_counts"],
            {
                "accepted": 1,
                "rejected": {
                    "invalid_outbox_rows": 0,
                    "invalid_ledger_rows": 0,
                    "invalid_receipts": 0,
                },
                "duplicate": None,
                "conflict": {"outbox_conflict_rows": 0, "ledger_conflict_rows": 0},
            },
        )
        self.assertEqual(
            report["unavailable_count_reasons"]["duplicate"],
            "duplicate_occurrence_not_durably_recorded",
        )
        self.assertEqual(hashlib.sha256(self.outbox.read_bytes()).hexdigest(), outbox_hash)
        self.assertEqual(hashlib.sha256(self.ledger.read_bytes()).hexdigest(), ledger_hash)
        report_text = json.dumps(report, sort_keys=True)
        self.assertNotIn(self.event["event_ref"], report_text)
        self.assertNotIn(self.event["payload_hash"], report_text)

    def test_evidence_report_attaches_transport_without_aggregating_it_as_evidence(self):
        evidence_root = self.root / "evaluator"
        evidence_dir = evidence_root / "operational-evidence"
        evidence_dir.mkdir(parents=True)
        assessment = json.loads(
            (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "evidence-valid.json")
            .read_text(encoding="utf-8")
        )
        assessment["assessment_id"] = "synthetic-assessment-only"
        assessment["environment_class"] = "production-like"
        assessment["integrity_hash"] = "sha256:" + hashlib.sha256(
            json.dumps(
                {key: value for key, value in assessment.items() if key != "integrity_hash"},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        (evidence_dir / "assessment.jsonl").write_text(
            json.dumps(assessment) + "\n", encoding="utf-8"
        )
        outbox_hash = hashlib.sha256(self.outbox.read_bytes()).hexdigest()
        ledger_hash = hashlib.sha256(self.ledger.read_bytes()).hexdigest()

        result = evidence_report.report(
            evidence_root,
            runtime_outbox_db_path=self.outbox,
            runtime_ledger_db_path=self.ledger,
            runtime_sink_id=SINK_ID,
            runtime_max_records=100,
        )

        self.assertEqual(result["stats"]["records_considered"], 1)
        self.assertEqual(
            [record["assessment_id"] for record in result["records"]],
            ["synthetic-assessment-only"],
        )
        transport_counts = result["runtime_transport"]["counts"]
        self.assertEqual(transport_counts["outbox_persisted"], 1)
        self.assertEqual(transport_counts["ledger_persisted"], 1)
        self.assertEqual(transport_counts["consumer_acknowledged"], 1)
        self.assertEqual(transport_counts["report_visible"], 1)
        outcome_counts = result["runtime_transport"]["outcome_counts"]
        self.assertEqual(outcome_counts["accepted"], 1)
        self.assertIsNone(outcome_counts["duplicate"])
        self.assertEqual(transport_counts["structurally_transport_only"], 1)
        self.assertIsNone(transport_counts["emitted"])
        self.assertIsNone(transport_counts["measurement_complete"])
        self.assertIsNone(transport_counts["evaluation_eligible"])
        self.assertFalse(result["runtime_transport"]["claims"]["promotion_input"])
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn(self.event["event_ref"], rendered)
        self.assertNotIn(str(self.outbox), rendered)
        self.assertNotIn(str(self.ledger), rendered)
        self.assertEqual(hashlib.sha256(self.outbox.read_bytes()).hexdigest(), outbox_hash)
        self.assertEqual(hashlib.sha256(self.ledger.read_bytes()).hexdigest(), ledger_hash)

        without_transport = evidence_report.report(evidence_root)
        self.assertNotIn("runtime_transport", without_transport)
        self.assertEqual(without_transport["records"], result["records"])
        self.assertEqual(without_transport["stats"], result["stats"])

    def test_evidence_report_requires_all_transport_arguments_together(self):
        with self.assertRaisesRegex(ValueError, "all four runtime transport arguments"):
            evidence_report.report(self.root, runtime_outbox_db_path=self.outbox)

    def test_evidence_report_cli_summary_includes_explicit_transport_subreport(self):
        stdout = StringIO()
        with patch.object(
            sys,
            "argv",
            [
                "evidence_report.py",
                "--root",
                str(self.root),
                "--summary",
                "--runtime-outbox-db",
                str(self.outbox),
                "--runtime-ledger-db",
                str(self.ledger),
                "--runtime-sink-id",
                SINK_ID,
                "--runtime-max-records",
                "100",
            ],
        ):
            with redirect_stdout(stdout):
                status = evidence_report.main()
        output = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(output["runtime_transport"]["counts"]["consumer_acknowledged"], 1)
        self.assertEqual(output["runtime_transport"]["outcome_counts"]["accepted"], 1)
        self.assertIsNone(output["runtime_transport"]["outcome_counts"]["duplicate"])
        self.assertIsNone(output["runtime_transport"]["counts"]["emitted"])

    def test_evidence_report_cli_entrypoint_runs_from_outside_repository(self):
        command = [
            sys.executable,
            str(ROOT / "scripts" / "evidence_report.py"),
            "--root",
            str(self.root),
            "--summary",
            "--runtime-outbox-db",
            str(self.outbox),
            "--runtime-ledger-db",
            str(self.ledger),
            "--runtime-sink-id",
            SINK_ID,
            "--runtime-max-records",
            "100",
        ]
        completed = subprocess.run(
            command,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertEqual(output["runtime_transport"]["counts"]["consumer_acknowledged"], 1)
        self.assertEqual(output["runtime_transport"]["outcome_counts"]["accepted"], 1)
        self.assertIsNone(output["runtime_transport"]["outcome_counts"]["duplicate"])
        self.assertIsNone(output["runtime_transport"]["counts"]["emitted"])
        self.assertNotIn(str(self.outbox), completed.stdout)
        self.assertNotIn(self.event["event_ref"], completed.stdout)

    def test_evidence_report_cli_rejects_partial_transport_arguments(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "evidence_report.py"),
                "--root",
                str(self.root),
                "--runtime-outbox-db",
                str(self.outbox),
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("all four --runtime-* arguments must be supplied together", completed.stderr)

    def test_conflict_counts_are_separate_by_store_and_exclude_event_refs(self):
        with sqlite3.connect(self.outbox) as conn:
            conn.execute(
                "INSERT INTO outbox_conflicts "
                "(event_ref, payload_hash, schema_version, candidate_sha256, envelope_json, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self.event["event_ref"],
                    self.event["payload_hash"],
                    2,
                    hashlib.sha256(b"outbox-candidate").hexdigest(),
                    b"{}",
                    "2026-10-20T12:02:00Z",
                ),
            )
        with sqlite3.connect(self.ledger) as conn:
            conn.execute(
                "INSERT INTO runtime_event_conflicts "
                "(event_ref, payload_hash, schema_version, candidate_sha256, envelope_json, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self.event["event_ref"],
                    self.event["payload_hash"],
                    2,
                    hashlib.sha256(b"ledger-candidate").hexdigest(),
                    b"{}",
                    "2026-10-20T12:02:00Z",
                ),
            )

        report = build_runtime_evidence_transport_report(
            self.outbox, self.ledger, sink_id=SINK_ID, max_records=100
        )
        self.assertEqual(
            report["outcome_counts"]["conflict"],
            {"outbox_conflict_rows": 1, "ledger_conflict_rows": 1},
        )
        self.assertNotIn(self.event["event_ref"], json.dumps(report, sort_keys=True))

    def test_same_event_ref_with_different_outbox_payload_is_not_counted_as_ack(self):
        other_outbox = self.root / "other-outbox.sqlite3"
        other_ledger = self.root / "other-ledger.sqlite3"
        other = _event(observed_at="2026-10-20T12:02:00Z")
        _create_outbox(other_outbox, [other])
        initialize_runtime_evidence_ledger(other_ledger)
        other_consumer = RuntimeEvidenceConsumer(
            other_ledger,
            sink_id=SINK_ID,
            clock=lambda: datetime(2026, 10, 20, 12, 3, tzinfo=timezone.utc),
        )
        other_consumer.consume_outbox_event(other_outbox, seq=1)

        report = build_runtime_evidence_transport_report(
            self.outbox, other_ledger, sink_id=SINK_ID, max_records=100
        )
        self.assertEqual(report["report_status"], "incomplete")
        self.assertEqual(report["counts"]["consumer_acknowledged"], 0)
        self.assertEqual(report["counts"]["outbox_to_ledger_exact"], 0)
        self.assertEqual(report["counts"]["outbox_pending_without_ledger"], 1)
        self.assertEqual(report["anomaly_counts"]["receipts_without_exact_outbox_row"], 1)

    def test_cli_requires_explicit_paths_and_prints_only_counts(self):
        stdout = StringIO()
        args = [
            "--outbox-db", str(self.outbox),
            "--ledger-db", str(self.ledger),
            "--sink-id", SINK_ID,
            "--max-records", "100",
        ]
        with redirect_stdout(stdout):
            status = report_main(args)
        report = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(report["counts"]["consumer_acknowledged"], 1)
        self.assertNotIn(self.event["event_ref"], stdout.getvalue())
        self.assertNotIn(str(self.ledger), stdout.getvalue())

    def test_bad_receipt_is_not_counted_as_consumer_ack(self):
        with sqlite3.connect(self.ledger) as conn:
            conn.execute(
                "UPDATE transport_receipts SET receipt_json=? WHERE sink_id=?",
                (b"{}", SINK_ID),
            )
        report = build_runtime_evidence_transport_report(
            self.outbox, self.ledger, sink_id=SINK_ID, max_records=100
        )
        self.assertEqual(report["report_status"], "incomplete")
        self.assertEqual(report["counts"]["consumer_acknowledged"], 0)
        self.assertEqual(report["anomaly_counts"]["invalid_receipts"], 1)
        self.assertEqual(report["outcome_counts"]["accepted"], 0)
        self.assertEqual(report["outcome_counts"]["rejected"]["invalid_receipts"], 1)

    def test_report_refuses_truncation_when_record_limit_is_exceeded(self):
        multiple_outbox = self.root / "multiple-outbox.sqlite3"
        _create_outbox(multiple_outbox, [_event("a"), _event("b")])
        with self.assertRaises(RuntimeEvidenceReportError) as raised:
            build_runtime_evidence_transport_report(
                multiple_outbox, self.ledger, sink_id=SINK_ID, max_records=1
            )
        self.assertEqual(raised.exception.code, "report_record_limit_exceeded")

    def test_report_streams_payload_bearing_rows(self):
        real_connect = transport_report._connect_readonly

        def streaming_connection(path):
            return _ConnectionProxy(real_connect(path))

        with patch.object(transport_report, "_connect_readonly", side_effect=streaming_connection):
            report = build_runtime_evidence_transport_report(
                self.outbox, self.ledger, sink_id=SINK_ID, max_records=100
            )
        self.assertEqual(report["counts"]["consumer_acknowledged"], 1)

    def test_same_database_cannot_be_used_for_both_boundaries(self):
        with self.assertRaises(RuntimeEvidenceReportError) as raised:
            build_runtime_evidence_transport_report(
                self.outbox, self.outbox, sink_id=SINK_ID, max_records=10
            )
        self.assertEqual(raised.exception.code, "database_paths_must_differ")

    def test_report_rejects_oversized_outbox_metadata_before_decoding(self):
        with sqlite3.connect(self.outbox) as conn:
            conn.execute(
                "UPDATE outbox_events SET event_ref=?, payload_hash=?",
                ("x" * (MAX_EVENT_REF_BYTES + 1), "x" * (MAX_PAYLOAD_HASH_BYTES + 1)),
            )
        with patch.object(transport_report, "_decode_envelope") as decode:
            with self.assertRaises(RuntimeEvidenceReportError) as raised:
                build_runtime_evidence_transport_report(
                    self.outbox, self.ledger, sink_id=SINK_ID, max_records=100
                )
            self.assertEqual(raised.exception.code, "report_record_size_exceeded")
            decode.assert_not_called()

    def test_report_rejects_oversized_ledger_metadata_before_decoding(self):
        with sqlite3.connect(self.ledger) as conn:
            conn.execute(
                "UPDATE runtime_events SET event_ref=?, payload_hash=?, record_hash=?",
                (
                    "x" * (MAX_EVENT_REF_BYTES + 1),
                    "x" * (MAX_PAYLOAD_HASH_BYTES + 1),
                    "x" * (MAX_RECORD_HASH_BYTES + 1),
                ),
            )
        with self.assertRaises(RuntimeEvidenceReportError) as raised:
            build_runtime_evidence_transport_report(
                self.outbox, self.ledger, sink_id=SINK_ID, max_records=100
            )
        self.assertEqual(raised.exception.code, "report_record_size_exceeded")

    def test_report_rejects_oversized_receipt_metadata_before_decoding(self):
        with sqlite3.connect(self.ledger) as conn:
            conn.execute(
                "UPDATE transport_receipts SET event_ref=?, payload_hash=? WHERE sink_id=?",
                ("x" * (MAX_EVENT_REF_BYTES + 1), "x" * (MAX_PAYLOAD_HASH_BYTES + 1), SINK_ID),
            )
        with self.assertRaises(RuntimeEvidenceReportError) as raised:
            build_runtime_evidence_transport_report(
                self.outbox, self.ledger, sink_id=SINK_ID, max_records=100
            )
        self.assertEqual(raised.exception.code, "report_record_size_exceeded")

    def test_report_rejects_multibyte_outbox_metadata_over_byte_limit(self):
        event_ref = "é" * (MAX_EVENT_REF_BYTES // 2 + 1)
        payload_hash = "é" * (MAX_PAYLOAD_HASH_BYTES // 2 + 1)
        with sqlite3.connect(self.outbox) as conn:
            conn.execute(
                "UPDATE outbox_events SET event_ref=?, payload_hash=?",
                (event_ref, payload_hash),
            )
        with patch.object(transport_report, "_decode_envelope") as decode:
            with self.assertRaises(RuntimeEvidenceReportError) as raised:
                build_runtime_evidence_transport_report(
                    self.outbox, self.ledger, sink_id=SINK_ID, max_records=100
                )
            self.assertEqual(raised.exception.code, "report_record_size_exceeded")
            decode.assert_not_called()

    def test_report_rejects_multibyte_ledger_metadata_over_byte_limit(self):
        event_ref = "é" * (MAX_EVENT_REF_BYTES // 2 + 1)
        payload_hash = "é" * (MAX_PAYLOAD_HASH_BYTES // 2 + 1)
        record_hash = "é" * (MAX_RECORD_HASH_BYTES // 2 + 1)
        with sqlite3.connect(self.ledger) as conn:
            conn.execute(
                "UPDATE runtime_events SET event_ref=?, payload_hash=?, record_hash=?",
                (event_ref, payload_hash, record_hash),
            )
        with patch.object(transport_report, "_decode_envelope", wraps=transport_report._decode_envelope) as decode:
            with self.assertRaises(RuntimeEvidenceReportError) as raised:
                build_runtime_evidence_transport_report(
                    self.outbox, self.ledger, sink_id=SINK_ID, max_records=100
                )
            self.assertEqual(raised.exception.code, "report_record_size_exceeded")
            # The valid Outbox row is decoded; oversized ledger metadata is rejected first.
            decode.assert_called_once()

    def test_report_rejects_multibyte_receipt_metadata_over_byte_limit(self):
        event_ref = "é" * (MAX_EVENT_REF_BYTES // 2 + 1)
        payload_hash = "é" * (MAX_PAYLOAD_HASH_BYTES // 2 + 1)
        with sqlite3.connect(self.ledger) as conn:
            conn.execute(
                "UPDATE transport_receipts SET event_ref=?, payload_hash=? WHERE sink_id=?",
                (event_ref, payload_hash, SINK_ID),
            )
        with patch.object(transport_report, "_validate_receipt") as validate_receipt:
            with self.assertRaises(RuntimeEvidenceReportError) as raised:
                build_runtime_evidence_transport_report(
                    self.outbox, self.ledger, sink_id=SINK_ID, max_records=100
                )
            self.assertEqual(raised.exception.code, "report_record_size_exceeded")
            validate_receipt.assert_not_called()

    def test_report_rejects_oversized_outbox_envelope_before_decoding(self):
        with sqlite3.connect(self.outbox) as conn:
            conn.execute(
                "UPDATE outbox_events SET envelope_json=zeroblob(?)",
                (MAX_ENVELOPE_BYTES + 1,),
            )
        with self.assertRaises(RuntimeEvidenceReportError) as raised:
            build_runtime_evidence_transport_report(
                self.outbox, self.ledger, sink_id=SINK_ID, max_records=100
            )
        self.assertEqual(raised.exception.code, "report_record_size_exceeded")

    def test_report_rejects_oversized_ledger_envelope_before_decoding(self):
        with sqlite3.connect(self.ledger) as conn:
            conn.execute(
                "UPDATE runtime_events SET envelope_json=zeroblob(?)",
                (MAX_ENVELOPE_BYTES + 1,),
            )
        with self.assertRaises(RuntimeEvidenceReportError) as raised:
            build_runtime_evidence_transport_report(
                self.outbox, self.ledger, sink_id=SINK_ID, max_records=100
            )
        self.assertEqual(raised.exception.code, "report_record_size_exceeded")

    def test_report_rejects_oversized_receipt_before_decoding(self):
        with sqlite3.connect(self.ledger) as conn:
            conn.execute(
                "UPDATE transport_receipts SET receipt_json=zeroblob(?) WHERE sink_id=?",
                (2049, SINK_ID),
            )
        with self.assertRaises(RuntimeEvidenceReportError) as raised:
            build_runtime_evidence_transport_report(
                self.outbox, self.ledger, sink_id=SINK_ID, max_records=100
            )
        self.assertEqual(raised.exception.code, "report_record_size_exceeded")


if __name__ == "__main__":
    unittest.main()
