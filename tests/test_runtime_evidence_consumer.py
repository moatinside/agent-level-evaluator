from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from scripts.runtime_evidence_consumer import (
    ConsumerError,
    RuntimeEvidenceConsumer,
    initialize_runtime_evidence_ledger,
    purge_expired_runtime_evidence_ledger,
)
from scripts.runtime_evidence_contract import canonical_json, seal_event, validate_event


def _event(event_char: str = "a", observed_at: str = "2026-10-20T12:00:00Z") -> dict:
    return seal_event({
        "schema_version": 2,
        "event_type": "turn_settled",
        "event_ref": "hmac-sha256:v1:" + event_char * 64,
        "observed_at": observed_at,
        "provenance": {
            "trigger_origin": "hermes_gateway",
            "source_class": "ordinary_runtime",
            "task_class": "ordinary_task",
            "classification_basis": "gateway_dispatch",
            "platform": "discord",
            "profile_ref": "hmac-sha256:v1:" + "b" * 64,
            "session_ref": "hmac-sha256:v1:" + "c" * 64,
            "episode_ref": "hmac-sha256:v1:" + "d" * 64,
            "scope_ref": "hmac-sha256:v1:" + "e" * 64,
        },
        "execution": {
            "execution_mode": "shadow",
            "terminal_status": "completed",
            "started_at": "2026-10-20T11:59:59Z",
            "ended_at": "2026-10-20T12:00:00Z",
            "persistence_status": "confirmed",
            "persistence_receipt_ref": "hmac-sha256:v1:" + "f" * 64,
            "delivery_status": "delivered",
            "runtime_build_id": "sha256:" + "1" * 64,
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
    })


def _create_outbox(path: Path, event: dict, *, columns: tuple | None = None, envelope: bytes | None = None) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE outbox_events ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, event_ref TEXT NOT NULL UNIQUE, "
            "payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, "
            "envelope_json BLOB NOT NULL, created_at TEXT NOT NULL);"
            "CREATE TABLE outbox_conflicts ("
            "conflict_id INTEGER PRIMARY KEY AUTOINCREMENT, event_ref TEXT NOT NULL, "
            "payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, candidate_sha256 TEXT NOT NULL, "
            "envelope_json BLOB NOT NULL, recorded_at TEXT NOT NULL, UNIQUE(event_ref, candidate_sha256));"
            "PRAGMA user_version=1;"
        )
        values = columns or (event["event_ref"], event["payload_hash"], 2)
        payload = envelope if envelope is not None else canonical_json(event)
        conn.execute(
            "INSERT INTO outbox_events(event_ref, payload_hash, schema_version, envelope_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (*values, payload, "2026-10-20T12:00:00Z"),
        )
    path.chmod(0o600)


def _create_same_version_malformed_outbox(path: Path, event: dict) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE outbox_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_ref TEXT NOT NULL, payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, "
            "envelope_json BLOB NOT NULL, created_at TEXT NOT NULL);"
            "CREATE TABLE outbox_conflicts (conflict_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_ref TEXT NOT NULL, payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, "
            "candidate_sha256 TEXT NOT NULL, envelope_json BLOB NOT NULL, recorded_at TEXT NOT NULL);"
            "PRAGMA user_version=1;"
        )
        conn.execute(
            "INSERT INTO outbox_events(event_ref, payload_hash, schema_version, envelope_json, created_at) "
            "VALUES (?, ?, 2, ?, ?)",
            (event["event_ref"], event["payload_hash"], canonical_json(event), "2026-10-20T12:00:00Z"),
        )
    path.chmod(0o600)


def _create_same_version_malformed_ledger(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE runtime_events (event_ref TEXT NOT NULL, payload_hash TEXT NOT NULL, "
            "schema_version INTEGER NOT NULL, envelope_json BLOB NOT NULL, record_hash TEXT NOT NULL, "
            "committed_at TEXT NOT NULL);"
            "CREATE TABLE runtime_event_conflicts (conflict_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_ref TEXT NOT NULL, payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, "
            "candidate_sha256 TEXT NOT NULL, envelope_json BLOB NOT NULL, recorded_at TEXT NOT NULL);"
            "CREATE TABLE transport_receipts (event_ref TEXT NOT NULL, payload_hash TEXT NOT NULL, "
            "schema_version INTEGER NOT NULL, sink_id TEXT NOT NULL, receipt_json BLOB NOT NULL);"
            "PRAGMA user_version=1;"
        )
    path.chmod(0o600)


class RuntimeEvidenceConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.outbox = self.root / "outbox.sqlite3"
        self.ledger = self.root / "ledger.sqlite3"
        self.event = _event()
        _create_outbox(self.outbox, self.event)
        self.consumer = RuntimeEvidenceConsumer(
            self.ledger,
            sink_id="fixture-ledger",
            clock=lambda: datetime(2026, 10, 20, 12, 1, tzinfo=timezone.utc),
        )

    def _add_acl(self, path: Path, *rules: str) -> None:
        for rule in rules:
            subprocess.run(["/bin/chmod", "+a", rule, str(path)], check=True, capture_output=True)
        # Deny-delete ACLs would block TemporaryDirectory cleanup; cleanups run LIFO.
        self.addCleanup(subprocess.run, ["/bin/chmod", "-N", str(path)], check=False, capture_output=True)

    def _consume(self, seq: int = 1):
        if type(seq) is int and seq == 1 and not self.ledger.exists():
            initialize_runtime_evidence_ledger(self.ledger)
        return self.consumer.consume_outbox_event(self.outbox, seq=seq)

    def test_commits_exact_row_then_persists_separate_ack_receipt(self):
        result = self._consume()

        self.assertEqual(result.status, "acknowledged")
        self.assertEqual(result.event_ref, self.event["event_ref"])
        self.assertEqual(result.payload_hash, self.event["payload_hash"])
        receipt = result.receipt or {}
        self.assertEqual(receipt["receipt_type"], "runtime_evidence_transport_ack")
        self.assertEqual(receipt["disposition"], "persisted")
        self.assertEqual(receipt["readback_status"], "exact_match")
        self.assertEqual(receipt["sink_id"], "fixture-ledger")
        self.assertEqual(receipt["ledger_record_hash"], "sha256:" + hashlib.sha256(canonical_json(self.event)).hexdigest())
        self.assertEqual(validate_event(self.event), ())
        self.assertEqual(self.event["assessment"]["evaluation_eligibility"], "transport_only")

        with sqlite3.connect(self.ledger) as conn:
            event_row = conn.execute(
                "SELECT event_ref, payload_hash, schema_version, envelope_json, record_hash "
                "FROM runtime_events"
            ).fetchone()
            receipt_row = conn.execute("SELECT receipt_json FROM transport_receipts").fetchone()
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runtime_event_conflicts").fetchone()[0], 0)
        self.assertEqual(event_row, (
            self.event["event_ref"], self.event["payload_hash"], 2,
            canonical_json(self.event), receipt["ledger_record_hash"],
        ))
        self.assertEqual(json.loads(receipt_row[0]), receipt)

    def test_retry_returns_existing_receipt_without_rewriting_rows(self):
        first = self._consume()
        with sqlite3.connect(self.ledger) as conn:
            before = conn.execute("SELECT receipt_json FROM transport_receipts").fetchone()[0]

        second = self._consume()

        self.assertEqual(second.status, "acknowledged")
        self.assertEqual(second.receipt, first.receipt)
        with sqlite3.connect(self.ledger) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0], 1)
            after = conn.execute("SELECT receipt_json FROM transport_receipts").fetchone()[0]
        self.assertEqual(before, after)

    def test_commit_without_readback_does_not_ack_and_retry_recovers(self):
        with patch("scripts.runtime_evidence_consumer._read_ledger_event", return_value=None):
            with self.assertRaises(ConsumerError) as raised:
                self._consume()
        self.assertEqual(raised.exception.code, "ledger_readback_mismatch")
        with sqlite3.connect(self.ledger) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0], 0)

        retry = self._consume()
        self.assertEqual(retry.status, "acknowledged")
        self.assertEqual((retry.receipt or {})["disposition"], "duplicate")

    def test_same_event_ref_different_payload_is_preserved_without_ack(self):
        changed = _event(observed_at="2026-10-20T12:00:03Z")
        second_outbox = self.root / "conflicting-outbox.sqlite3"
        _create_outbox(second_outbox, changed)
        self._consume()

        result = self.consumer.consume_outbox_event(second_outbox, seq=1)

        self.assertEqual(result.status, "conflict")
        self.assertIsNone(result.receipt)
        with sqlite3.connect(self.ledger) as conn:
            event_row = conn.execute("SELECT envelope_json FROM runtime_events").fetchone()[0]
            conflicts = conn.execute("SELECT envelope_json FROM runtime_event_conflicts").fetchall()
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0], 1)
        self.assertEqual(bytes(event_row), canonical_json(self.event))
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(bytes(conflicts[0][0]), canonical_json(changed))

    def test_outbox_is_read_only_and_unchanged(self):
        before = hashlib.sha256(self.outbox.read_bytes()).hexdigest()
        self._consume()
        after = hashlib.sha256(self.outbox.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_outbox_columns_must_match_the_canonical_envelope(self):
        mismatched = self.root / "mismatched.sqlite3"
        _create_outbox(
            mismatched,
            self.event,
            columns=(self.event["event_ref"], "sha256:" + "0" * 64, 2),
        )
        with self.assertRaises(ConsumerError) as raised:
            self.consumer.consume_outbox_event(mismatched, seq=1)
        self.assertEqual(raised.exception.code, "outbox_envelope_mismatch")
        self.assertFalse(self.ledger.exists())

    def test_invalid_or_noncanonical_event_is_rejected_before_ledger_write(self):
        invalid = dict(self.event)
        invalid["trace"] = dict(invalid["trace"], raw_text="synthetic-private-marker")
        invalid["payload_hash"] = "sha256:" + "0" * 64
        invalid_outbox = self.root / "invalid.sqlite3"
        _create_outbox(invalid_outbox, invalid)
        with self.assertRaises(ConsumerError) as raised:
            self.consumer.consume_outbox_event(invalid_outbox, seq=1)
        self.assertEqual(raised.exception.code, "event_rejected")
        self.assertIn("unknown_field", raised.exception.error_codes)
        self.assertFalse(self.ledger.exists())

        noncanonical_outbox = self.root / "noncanonical.sqlite3"
        noncanonical = json.dumps(self.event, ensure_ascii=False).encode("utf-8")
        _create_outbox(noncanonical_outbox, self.event, envelope=noncanonical)
        with self.assertRaises(ConsumerError) as noncanonical_error:
            self.consumer.consume_outbox_event(noncanonical_outbox, seq=1)
        self.assertEqual(noncanonical_error.exception.code, "event_noncanonical")
        self.assertFalse(self.ledger.exists())

    def test_consumer_requires_explicit_ledger_bootstrap_and_does_not_create_it(self):
        with self.assertRaises(ConsumerError) as raised:
            self.consumer.consume_outbox_event(self.outbox, seq=1)
        self.assertEqual(raised.exception.code, "database_unavailable")
        self.assertFalse(self.ledger.exists())

    def test_missing_or_invalid_outbox_row_does_not_create_ledger(self):
        with self.assertRaises(ConsumerError) as missing:
            self._consume(seq=2)
        self.assertEqual(missing.exception.code, "outbox_event_not_found")
        with self.assertRaises(ConsumerError) as invalid_seq:
            self._consume(seq=True)
        self.assertEqual(invalid_seq.exception.code, "outbox_sequence_invalid")
        self.assertFalse(self.ledger.exists())

    def test_database_roots_must_be_distinct_and_sink_id_explicit(self):
        with self.assertRaises(ConsumerError) as same_path:
            RuntimeEvidenceConsumer(self.outbox, sink_id="fixture-ledger").consume_outbox_event(self.outbox, seq=1)
        self.assertEqual(same_path.exception.code, "database_paths_must_differ")
        with self.assertRaises(ConsumerError) as bad_sink:
            RuntimeEvidenceConsumer(self.ledger, sink_id="not an id")
        self.assertEqual(bad_sink.exception.code, "sink_id_invalid")

    def test_receipt_write_readback_race_uses_existing_exact_receipt(self):
        consumer = RuntimeEvidenceConsumer(
            self.ledger,
            sink_id="fixture-ledger",
            clock=lambda: datetime(2026, 10, 20, 12, 2, tzinfo=timezone.utc),
        )
        first = self._consume()
        original_read_receipt = __import__("scripts.runtime_evidence_consumer", fromlist=["_read_receipt"])._read_receipt
        call_count = {"value": 0}

        def first_read_missing_then_real(path, event_ref, payload_hash, sink_id):
            call_count["value"] += 1
            if call_count["value"] == 1:
                return None
            return original_read_receipt(path, event_ref, payload_hash, sink_id)

        with patch("scripts.runtime_evidence_consumer._read_receipt", side_effect=first_read_missing_then_real):
            result = consumer._persist_and_ack(self.event, canonical_json(self.event))
        self.assertEqual(result.status, "acknowledged")
        self.assertEqual(result.receipt, first.receipt)

    def test_concurrent_duplicate_consumers_produce_one_event_and_one_receipt(self):
        results = []
        failures = []

        def run():
            try:
                results.append(self._consume())
            except Exception as exc:
                failures.append(getattr(exc, "code", type(exc).__name__))

        workers = [Thread(target=run) for _ in range(4)]
        initialize_runtime_evidence_ledger(self.ledger)
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 4)
        self.assertTrue(all(result.status == "acknowledged" for result in results))
        with sqlite3.connect(self.ledger) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0], 1)

    def test_separate_processes_contend_on_sqlite_and_ack_once(self):
        initialize_runtime_evidence_ledger(self.ledger)
        root = Path(__file__).resolve().parents[1]
        gate = self.root / "release-processes"
        ready = [self.root / f"ready-{index}" for index in range(2)]
        attempting = [self.root / f"attempting-{index}" for index in range(2)]
        script = r'''import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import scripts.runtime_evidence_consumer as module
outbox, ledger, ready, gate, attempting = map(Path, sys.argv[1:])
original = module._connect_writer
class ConnectionProxy:
    def __init__(self, connection): self.connection, self.marked = connection, False
    def execute(self, sql, *args):
        if sql == "BEGIN IMMEDIATE" and not self.marked:
            attempting.write_text("arrived", encoding="ascii")
            self.marked = True
        return self.connection.execute(sql, *args)
    def __getattr__(self, name): return getattr(self.connection, name)
def connect_writer(path, *, create): return ConnectionProxy(original(path, create=create))
module._connect_writer = connect_writer
ready.touch()
deadline = time.monotonic() + 15
while not gate.exists():
    if time.monotonic() >= deadline: raise SystemExit(91)
    time.sleep(0.005)
consumer = module.RuntimeEvidenceConsumer(ledger, sink_id="fixture-ledger", clock=lambda: datetime(2026, 10, 20, 12, 1, tzinfo=timezone.utc))
result = consumer.consume_outbox_event(outbox, seq=1)
print(json.dumps({"status": result.status}))
'''
        locker = sqlite3.connect(self.ledger, timeout=5, isolation_level=None)
        locker.execute("BEGIN IMMEDIATE")
        processes = []
        barrier_error = None
        try:
            for index in range(2):
                processes.append(subprocess.Popen(
                    [sys.executable, "-c", script, str(self.outbox), str(self.ledger),
                     str(ready[index]), str(gate), str(attempting[index])],
                    cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                ))
            deadline = time.monotonic() + 10
            while not all(path.exists() for path in ready):
                if time.monotonic() >= deadline:
                    barrier_error = "consumer processes did not reach the release barrier"
                    break
                time.sleep(0.005)
            if barrier_error is None:
                gate.touch()
                deadline = time.monotonic() + 10
                while not all(path.exists() for path in attempting):
                    if time.monotonic() >= deadline:
                        barrier_error = "consumer processes did not reach BEGIN IMMEDIATE"
                        break
                    time.sleep(0.005)
                if barrier_error is None:
                    time.sleep(0.05)
                    if any(process.poll() is not None for process in processes):
                        barrier_error = "consumer process completed while the SQLite writer lock was held"
        finally:
            if locker.in_transaction:
                locker.rollback()
            locker.close()
            gate.touch()

        outputs = []
        try:
            outputs = [process.communicate(timeout=15) for process in processes]
        except subprocess.TimeoutExpired:
            for process in processes:
                if process.poll() is None:
                    process.kill()
            outputs = [process.communicate() for process in processes]
            self.fail("consumer process did not finish after releasing the SQLite lock")
        self.assertIsNone(barrier_error, barrier_error)
        self.assertEqual([process.returncode for process in processes], [0, 0], outputs)
        self.assertEqual([json.loads(stdout)["status"] for stdout, _ in outputs], ["acknowledged", "acknowledged"])
        with sqlite3.connect(self.ledger) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0], 1)

    def test_process_exit_after_ledger_commit_before_ack_recovers(self):
        initialize_runtime_evidence_ledger(self.ledger)
        root = Path(__file__).resolve().parents[1]
        script = r'''import os, sys
import scripts.runtime_evidence_consumer as module
def terminate_before_readback(*args, **kwargs): os._exit(73)
module._read_ledger_event = terminate_before_readback
module.RuntimeEvidenceConsumer(sys.argv[2], sink_id="fixture-ledger").consume_outbox_event(sys.argv[1], seq=1)
'''
        crashed = subprocess.run(
            [sys.executable, "-c", script, str(self.outbox), str(self.ledger)],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(crashed.returncode, 73, crashed.stderr)
        with sqlite3.connect(self.ledger) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0], 0)

        retry = self.consumer.consume_outbox_event(self.outbox, seq=1)
        self.assertEqual(retry.status, "acknowledged")
        self.assertEqual((retry.receipt or {})["disposition"], "duplicate")
        with sqlite3.connect(self.ledger) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0], 1)

    def test_process_exit_after_receipt_commit_recovers_existing_ack(self):
        initialize_runtime_evidence_ledger(self.ledger)
        root = Path(__file__).resolve().parents[1]
        script = r'''import os, sys
import scripts.runtime_evidence_consumer as module
original = module._read_receipt
calls = {"count": 0}
def terminate_after_receipt_commit(*args, **kwargs):
    calls["count"] += 1
    if calls["count"] == 2: os._exit(75)
    return original(*args, **kwargs)
module._read_receipt = terminate_after_receipt_commit
module.RuntimeEvidenceConsumer(sys.argv[2], sink_id="fixture-ledger").consume_outbox_event(sys.argv[1], seq=1)
'''
        crashed = subprocess.run(
            [sys.executable, "-c", script, str(self.outbox), str(self.ledger)],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(crashed.returncode, 75, crashed.stderr)
        with sqlite3.connect(self.ledger) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0], 1)

        retry = self.consumer.consume_outbox_event(self.outbox, seq=1)
        self.assertEqual(retry.status, "acknowledged")
        self.assertEqual((retry.receipt or {})["disposition"], "persisted")
        with sqlite3.connect(self.ledger) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0], 1)

    def test_ledger_bootstrap_creates_private_file_under_restrictive_umask(self):
        path = self.root / "private-ledger.sqlite3"
        previous_umask = os.umask(0o077)
        try:
            initialize_runtime_evidence_ledger(path)
        finally:
            os.umask(previous_umask)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_ledger_bootstrap_rejects_unexpected_view_without_mutating_database(self):
        path = self.root / "view-only-ledger.sqlite3"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE VIEW unexpected_view AS SELECT 1 AS value")
        path.chmod(0o600)
        before = path.read_bytes()

        with self.assertRaises(ConsumerError) as raised:
            initialize_runtime_evidence_ledger(path)

        self.assertEqual(raised.exception.code, "ledger_schema_unsupported")
        self.assertEqual(path.read_bytes(), before)

    def test_receipt_schema_refuses_python_boolean_for_integer_constant(self):
        result = self._consume()
        bad = dict(result.receipt or {}, receipt_schema_version=True)
        from scripts.runtime_evidence_consumer import _validate_receipt
        self.assertFalse(_validate_receipt(bad))

    def test_same_version_malformed_outbox_schema_is_read_only_rejected(self):
        malformed = self.root / "malformed-outbox.sqlite3"
        _create_same_version_malformed_outbox(malformed, self.event)
        before = hashlib.sha256(malformed.read_bytes()).hexdigest()

        with self.assertRaises(ConsumerError) as raised:
            self.consumer.consume_outbox_event(malformed, seq=1)

        self.assertEqual(raised.exception.code, "outbox_schema_unsupported")
        self.assertEqual(hashlib.sha256(malformed.read_bytes()).hexdigest(), before)
        self.assertFalse(self.ledger.exists())

    def test_same_version_malformed_ledger_schema_is_rejected_without_migration(self):
        malformed = self.root / "malformed-ledger.sqlite3"
        _create_same_version_malformed_ledger(malformed)
        before = hashlib.sha256(malformed.read_bytes()).hexdigest()
        consumer = RuntimeEvidenceConsumer(malformed, sink_id="fixture-ledger")

        with self.assertRaises(ConsumerError) as raised:
            consumer.consume_outbox_event(self.outbox, seq=1)

        self.assertEqual(raised.exception.code, "ledger_schema_unsupported")
        self.assertEqual(hashlib.sha256(malformed.read_bytes()).hexdigest(), before)

    def test_same_version_outbox_rejects_sqlite_like_named_extra_table(self):
        initialize_runtime_evidence_ledger(self.ledger)
        with sqlite3.connect(self.outbox) as conn:
            conn.execute("CREATE TABLE sqliteX_extra (value TEXT)")
        self.outbox.chmod(0o600)
        outbox_before = self.outbox.read_bytes()
        ledger_before = self.ledger.read_bytes()

        with self.assertRaises(ConsumerError) as raised:
            self.consumer.consume_outbox_event(self.outbox, seq=1)

        self.assertEqual(raised.exception.code, "outbox_schema_unsupported")
        self.assertEqual(self.outbox.read_bytes(), outbox_before)
        self.assertEqual(self.ledger.read_bytes(), ledger_before)

    def test_same_version_ledger_rejects_sqlite_like_named_extra_table(self):
        initialize_runtime_evidence_ledger(self.ledger)
        with sqlite3.connect(self.ledger) as conn:
            conn.execute("CREATE TABLE sqliteX_extra (value TEXT)")
        self.ledger.chmod(0o600)
        before = self.ledger.read_bytes()

        with self.assertRaises(ConsumerError) as raised:
            self.consumer.consume_outbox_event(self.outbox, seq=1)

        self.assertEqual(raised.exception.code, "ledger_schema_unsupported")
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_same_version_outbox_rejects_unexpected_check_constraint_before_write(self):
        malformed = self.root / "checked-outbox.sqlite3"
        with sqlite3.connect(malformed) as conn:
            conn.executescript(
                "CREATE TABLE outbox_events ("
                "seq INTEGER PRIMARY KEY AUTOINCREMENT, event_ref TEXT NOT NULL UNIQUE, "
                "payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL CHECK(schema_version=3), "
                "envelope_json BLOB NOT NULL, created_at TEXT NOT NULL);"
                "CREATE TABLE outbox_conflicts ("
                "conflict_id INTEGER PRIMARY KEY AUTOINCREMENT, event_ref TEXT NOT NULL, "
                "payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, candidate_sha256 TEXT NOT NULL, "
                "envelope_json BLOB NOT NULL, recorded_at TEXT NOT NULL, UNIQUE(event_ref, candidate_sha256));"
                "PRAGMA user_version=1;"
            )
        malformed.chmod(0o600)
        before = malformed.read_bytes()
        ledger_before = self.ledger.read_bytes() if self.ledger.exists() else None

        with self.assertRaises(ConsumerError) as raised:
            self.consumer.consume_outbox_event(malformed, seq=1)

        self.assertEqual(raised.exception.code, "outbox_schema_unsupported")
        self.assertEqual(malformed.read_bytes(), before)
        self.assertEqual(self.ledger.read_bytes() if self.ledger.exists() else None, ledger_before)

    def test_same_version_outbox_rejects_unexpected_custom_index_before_write(self):
        initialize_runtime_evidence_ledger(self.ledger)
        with sqlite3.connect(self.outbox) as conn:
            conn.execute("CREATE INDEX outbox_unexpected_index ON outbox_events(schema_version)")
        self.outbox.chmod(0o600)
        outbox_before = self.outbox.read_bytes()
        ledger_before = self.ledger.read_bytes()

        with self.assertRaises(ConsumerError) as raised:
            self.consumer.consume_outbox_event(self.outbox, seq=1)

        self.assertEqual(raised.exception.code, "outbox_schema_unsupported")
        self.assertEqual(self.outbox.read_bytes(), outbox_before)
        self.assertEqual(self.ledger.read_bytes(), ledger_before)

    def test_same_version_ledger_rejects_unexpected_check_constraint_before_write(self):
        malformed = self.root / "checked-ledger.sqlite3"
        with sqlite3.connect(malformed) as conn:
            conn.executescript(
                "CREATE TABLE runtime_events ("
                "event_ref TEXT NOT NULL PRIMARY KEY, payload_hash TEXT NOT NULL, "
                "schema_version INTEGER NOT NULL CHECK(schema_version=3), envelope_json BLOB NOT NULL, "
                "record_hash TEXT NOT NULL, committed_at TEXT NOT NULL);"
                "CREATE TABLE runtime_event_conflicts ("
                "conflict_id INTEGER PRIMARY KEY AUTOINCREMENT, event_ref TEXT NOT NULL, "
                "payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, candidate_sha256 TEXT NOT NULL, "
                "envelope_json BLOB NOT NULL, recorded_at TEXT NOT NULL, UNIQUE(event_ref, candidate_sha256));"
                "CREATE TABLE transport_receipts ("
                "event_ref TEXT NOT NULL, payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, "
                "sink_id TEXT NOT NULL, receipt_json BLOB NOT NULL, "
                "PRIMARY KEY(event_ref, payload_hash, schema_version, sink_id));"
                "PRAGMA user_version=1;"
            )
        malformed.chmod(0o600)
        before = malformed.read_bytes()
        consumer = RuntimeEvidenceConsumer(malformed, sink_id="fixture-ledger")

        with self.assertRaises(ConsumerError) as raised:
            consumer.consume_outbox_event(self.outbox, seq=1)

        self.assertEqual(raised.exception.code, "ledger_schema_unsupported")
        self.assertEqual(malformed.read_bytes(), before)

    def test_same_version_ledger_rejects_extra_unique_index_before_write(self):
        initialize_runtime_evidence_ledger(self.ledger)
        existing = _event(event_char="g")
        with sqlite3.connect(self.ledger) as conn:
            conn.execute(
                "INSERT INTO runtime_events "
                "(event_ref, payload_hash, schema_version, envelope_json, record_hash, committed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (existing["event_ref"], existing["payload_hash"], 2, canonical_json(existing),
                 "sha256:" + hashlib.sha256(canonical_json(existing)).hexdigest(), "2026-10-20T12:00:00Z"),
            )
            conn.execute(
                "CREATE UNIQUE INDEX ledger_unexpected_one_event_per_schema "
                "ON runtime_events(schema_version) WHERE schema_version=2"
            )
        self.ledger.chmod(0o600)
        before = self.ledger.read_bytes()

        with self.assertRaises(ConsumerError) as raised:
            self.consumer.consume_outbox_event(self.outbox, seq=1)

        self.assertEqual(raised.exception.code, "ledger_schema_unsupported")
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_ledger_insert_failure_rolls_back_and_next_consume_recovers(self):
        import scripts.runtime_evidence_consumer as consumer_module

        initialize_runtime_evidence_ledger(self.ledger)
        before = self.ledger.read_bytes()
        original = consumer_module._connect_writer
        observed = []

        class FailAfterInsert:
            def __init__(self, connection):
                self.connection = connection
                self.injected = False

            def execute(self, sql, *args):
                result = self.connection.execute(sql, *args)
                if sql.startswith("INSERT INTO runtime_events") and not self.injected:
                    self.injected = True
                    raise sqlite3.OperationalError("synthetic failure")
                return result

            def rollback(self):
                self.connection.rollback()
                observed.append(self.connection.in_transaction)

            def __getattr__(self, name):
                return getattr(self.connection, name)

        def connect_writer(path, *, create):
            connection = original(path, create=create)
            return FailAfterInsert(connection) if Path(path) == self.ledger else connection

        with patch("scripts.runtime_evidence_consumer._connect_writer", side_effect=connect_writer):
            with self.assertRaises(ConsumerError) as raised:
                self.consumer.consume_outbox_event(self.outbox, seq=1)

        self.assertEqual(raised.exception.code, "ledger_write_unavailable")
        self.assertEqual(observed, [False])
        self.assertEqual(self.ledger.read_bytes(), before)
        with sqlite3.connect(self.ledger) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0], 0)

        recovered = self.consumer.consume_outbox_event(self.outbox, seq=1)
        self.assertEqual(recovered.status, "acknowledged")
        self.assertEqual((recovered.receipt or {})["disposition"], "persisted")
        with sqlite3.connect(self.ledger) as conn:
            row = conn.execute("SELECT event_ref, envelope_json FROM runtime_events").fetchone()
        self.assertEqual(row, (self.event["event_ref"], canonical_json(self.event)))

    def test_receipt_insert_failure_preserves_ledger_then_recovers_ack(self):
        import scripts.runtime_evidence_consumer as consumer_module

        initialize_runtime_evidence_ledger(self.ledger)
        original = consumer_module._connect_writer
        observed = []

        class FailAfterInsert:
            def __init__(self, connection):
                self.connection = connection
                self.injected = False

            def execute(self, sql, *args):
                result = self.connection.execute(sql, *args)
                if sql.startswith("INSERT INTO transport_receipts") and not self.injected:
                    self.injected = True
                    raise sqlite3.OperationalError("synthetic failure")
                return result

            def rollback(self):
                self.connection.rollback()
                observed.append(self.connection.in_transaction)

            def __getattr__(self, name):
                return getattr(self.connection, name)

        def connect_writer(path, *, create):
            connection = original(path, create=create)
            return FailAfterInsert(connection) if Path(path) == self.ledger else connection

        with patch("scripts.runtime_evidence_consumer._connect_writer", side_effect=connect_writer):
            with self.assertRaises(ConsumerError) as raised:
                self.consumer.consume_outbox_event(self.outbox, seq=1)

        self.assertEqual(raised.exception.code, "receipt_write_unavailable")
        self.assertEqual(observed, [False])
        with sqlite3.connect(self.ledger) as conn:
            event_row = conn.execute(
                "SELECT event_ref, envelope_json FROM runtime_events"
            ).fetchone()
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0], 0)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(event_row, (self.event["event_ref"], canonical_json(self.event)))

        recovered = self.consumer.consume_outbox_event(self.outbox, seq=1)
        self.assertEqual(recovered.status, "acknowledged")
        self.assertEqual((recovered.receipt or {})["disposition"], "duplicate")
        with sqlite3.connect(self.ledger) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0], 1)


    def test_sqlite_page_limit_withholds_ack_then_consume_recovers(self):
        import scripts.runtime_evidence_consumer as consumer_module

        initialize_runtime_evidence_ledger(self.ledger)
        with sqlite3.connect(self.ledger) as conn:
            initial_pages = conn.execute("PRAGMA page_count").fetchone()[0]
        limits = {"pages": initial_pages}
        original = consumer_module._connect_writer
        full_signals = []

        class ObserveFull:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql, *args):
                try:
                    return self.connection.execute(sql, *args)
                except sqlite3.Error as exc:
                    code = getattr(exc, "sqlite_errorcode", None)
                    full_signals.append(
                        (code is not None and code & 0xFF == sqlite3.SQLITE_FULL)
                        or "full" in str(exc).lower()
                    )
                    raise

            def commit(self):
                try:
                    return self.connection.commit()
                except sqlite3.Error as exc:
                    code = getattr(exc, "sqlite_errorcode", None)
                    full_signals.append(
                        (code is not None and code & 0xFF == sqlite3.SQLITE_FULL)
                        or "full" in str(exc).lower()
                    )
                    raise

            def __getattr__(self, name):
                return getattr(self.connection, name)

        def connect_with_page_limit(path, *, create):
            conn = original(path, create=create)
            if Path(path) == self.ledger:
                conn.execute(f"PRAGMA max_page_count={limits['pages']}")
                return ObserveFull(conn)
            return conn

        successful_acks = 0
        failed_event = None
        failed_outbox = None
        failure_code = None
        with patch("scripts.runtime_evidence_consumer._connect_writer", side_effect=connect_with_page_limit):
            for index in range(1, 128):
                event = _event()
                event["event_ref"] = "hmac-sha256:v1:" + format(index, "064x")
                event.pop("payload_hash")
                event = seal_event(event)
                outbox = self.root / f"page-limited-outbox-{index}.sqlite3"
                _create_outbox(outbox, event)
                try:
                    result = self.consumer.consume_outbox_event(outbox, seq=1)
                except ConsumerError as exc:
                    failure_code = exc.code
                    failed_event = event
                    failed_outbox = outbox
                    break
                self.assertEqual(result.status, "acknowledged")
                successful_acks += 1

            self.assertGreater(successful_acks, 0)
            self.assertIsNotNone(failed_event)
            self.assertIsNotNone(failed_outbox)
            assert failed_event is not None
            assert failed_outbox is not None
            self.assertIn(failure_code, {"ledger_write_unavailable", "receipt_write_unavailable"})
            self.assertIn(True, full_signals)
            with sqlite3.connect(self.ledger) as conn:
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertLessEqual(conn.execute("PRAGMA page_count").fetchone()[0], initial_pages)
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM transport_receipts WHERE event_ref=?",
                        (failed_event["event_ref"],),
                    ).fetchone()[0],
                    0,
                )

            limits["pages"] = 2_147_483_646
            recovered = self.consumer.consume_outbox_event(failed_outbox, seq=1)
            self.assertEqual(recovered.status, "acknowledged")
            with sqlite3.connect(self.ledger) as conn:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0],
                    successful_acks + 1,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0],
                    successful_acks + 1,
                )
                row = conn.execute(
                    "SELECT event_ref, payload_hash, schema_version, envelope_json "
                    "FROM runtime_events WHERE event_ref=?", (failed_event["event_ref"],)
                ).fetchone()
            self.assertEqual(
                row,
                (failed_event["event_ref"], failed_event["payload_hash"], 2, canonical_json(failed_event)),
            )


    def test_readonly_uris_escape_reserved_paths_and_reject_writes(self):
        import scripts.runtime_evidence_consumer as consumer_module

        outbox = self.root / "runtime outbox #?% fixture.sqlite3"
        ledger = self.root / "runtime ledger #?% fixture.sqlite3"
        _create_outbox(outbox, self.event)
        initialize_runtime_evidence_ledger(ledger)
        consumer = RuntimeEvidenceConsumer(ledger, sink_id="fixture-ledger")

        result = consumer.consume_outbox_event(outbox, seq=1)

        self.assertEqual(result.status, "acknowledged")
        self.assertEqual(result.event_ref, self.event["event_ref"])
        for path, table in ((outbox, "outbox_events"), (ledger, "runtime_events")):
            conn = consumer_module._connect_readonly(path)
            try:
                self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    conn.execute(f"DELETE FROM {table}")
            finally:
                conn.close()
        with sqlite3.connect(outbox) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM outbox_events").fetchone()[0], 1)
        with sqlite3.connect(ledger) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0], 1)


    def test_ledger_bootstrap_rejects_group_or_world_writable_parent(self):
        unsafe = self.root / "unsafe-parent"
        unsafe.mkdir()
        unsafe.chmod(0o777)
        path = unsafe / "ledger.sqlite3"

        with self.assertRaises(ConsumerError) as raised:
            initialize_runtime_evidence_ledger(path)

        self.assertEqual(raised.exception.code, "database_permissions_invalid")
        self.assertFalse(path.exists())

    def test_ledger_bootstrap_rejects_symlinked_parent(self):
        target = self.root / "actual-parent"
        target.mkdir()
        alias = self.root / "parent-alias"
        alias.symlink_to(target, target_is_directory=True)
        path = alias / "ledger.sqlite3"

        with self.assertRaises(ConsumerError) as raised:
            initialize_runtime_evidence_ledger(path)

        self.assertEqual(raised.exception.code, "database_path_invalid")
        self.assertFalse((target / "ledger.sqlite3").exists())

    def test_ledger_bootstrap_rejects_parent_path_with_dotdot(self):
        path = self.root / "nonexistent" / ".." / "ledger.sqlite3"

        with self.assertRaises(ConsumerError) as raised:
            initialize_runtime_evidence_ledger(path)

        self.assertEqual(raised.exception.code, "database_path_invalid")
        self.assertFalse((self.root / "ledger.sqlite3").exists())

    @unittest.skipUnless(sys.platform == "darwin", "macOS extended ACL behavior")
    def test_ledger_bootstrap_rejects_parent_directory_with_extended_acl(self):
        parent = self.root / "acl-parent"
        parent.mkdir()
        subprocess.run(
            ["/bin/chmod", "+a", "everyone allow search", str(parent)],
            check=True,
            capture_output=True,
        )
        path = parent / "ledger.sqlite3"

        with self.assertRaises(ConsumerError) as raised:
            initialize_runtime_evidence_ledger(path)

        self.assertEqual(raised.exception.code, "database_permissions_invalid")
        self.assertFalse(path.exists())

    @unittest.skipUnless(sys.platform == "darwin", "macOS extended ACL behavior")
    def test_ledger_bootstrap_accepts_parent_directory_with_deny_only_acl(self):
        # macOS puts ``group:everyone deny delete`` on every home directory.
        parent = self.root / "deny-acl-parent"
        parent.mkdir()
        self._add_acl(parent, "group:everyone deny delete")
        path = parent / "ledger.sqlite3"

        initialize_runtime_evidence_ledger(path)

        self.assertTrue(path.exists())
        self.assertEqual(stat.S_IMODE(path.lstat().st_mode), 0o600)

    @unittest.skipUnless(sys.platform == "darwin", "macOS extended ACL behavior")
    def test_ledger_bootstrap_rejects_parent_directory_with_mixed_deny_and_allow_acl(self):
        parent = self.root / "mixed-acl-parent"
        parent.mkdir()
        self._add_acl(parent, "group:everyone deny delete", "group:everyone allow write")
        path = parent / "ledger.sqlite3"

        with self.assertRaises(ConsumerError) as raised:
            initialize_runtime_evidence_ledger(path)

        self.assertEqual(raised.exception.code, "database_permissions_invalid")
        self.assertFalse(path.exists())

    @unittest.skipUnless(sys.platform == "darwin", "macOS extended ACL behavior")
    def test_ledger_rejects_deny_only_acl_on_database_file(self):
        path = self.root / "deny-acl-file-ledger.sqlite3"
        initialize_runtime_evidence_ledger(path)
        self._add_acl(path, "group:everyone deny delete")
        before = path.read_bytes()

        with self.assertRaises(ConsumerError) as raised:
            initialize_runtime_evidence_ledger(path)

        self.assertEqual(raised.exception.code, "database_permissions_invalid")
        self.assertEqual(path.read_bytes(), before)

    @unittest.skipUnless(sys.platform == "darwin", "macOS extended ACL behavior")
    def test_parent_acl_entry_query_failure_fails_closed(self):
        import ctypes
        import errno

        import scripts.runtime_evidence_consumer as consumer_module

        parent = self.root / "deny-acl-parent"
        parent.mkdir()
        self._add_acl(parent, "group:everyone deny delete")
        real_api = consumer_module._DARWIN_ACL_API

        class _FailingTagApi:
            def __getattr__(self, name):
                return getattr(real_api, name)

            def acl_get_tag_type(self, entry, tag):
                ctypes.set_errno(errno.EIO)
                return -1

        path = parent / "ledger.sqlite3"
        with patch.object(consumer_module, "_DARWIN_ACL_API", _FailingTagApi()):
            with self.assertRaises(ConsumerError) as raised:
                initialize_runtime_evidence_ledger(path)

        self.assertEqual(raised.exception.code, "database_permissions_invalid")
        self.assertFalse(path.exists())

    @unittest.skipUnless(sys.platform == "darwin", "macOS extended ACL behavior")
    def test_canonical_runtime_root_parent_chain_is_accepted_read_only(self):
        import scripts.runtime_evidence_consumer as consumer_module

        root = Path("/Users/yokapro/.hermes/runtime-evidence/agent-level/v2")
        if not root.is_dir():
            self.skipTest("canonical runtime root absent on this host")

        consumer_module._validate_parent_chain(root)

    @unittest.skipUnless(sys.platform == "darwin", "macOS extended ACL behavior")
    def test_file_acl_is_rejected_and_acl_query_preserves_sqlite_lock(self):
        import scripts.runtime_evidence_consumer as consumer_module

        path = self.root / "acl-file-ledger.sqlite3"
        initialize_runtime_evidence_ledger(path)
        holder = sqlite3.connect(path, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        try:
            subprocess.run(
                ["/bin/chmod", "+a", "everyone allow read", str(path)],
                check=True,
                capture_output=True,
            )
            self.assertEqual(stat.S_IMODE(path.lstat().st_mode), 0o600)
            self.assertTrue(consumer_module._has_extended_acl(path))
            child_code = (
                "import sqlite3,sys; c=sqlite3.connect(sys.argv[1],timeout=.1,isolation_level=None); "
                "\ntry: c.execute('BEGIN IMMEDIATE'); print('ACQUIRED') "
                "\nexcept sqlite3.OperationalError: print('BUSY') "
                "\nfinally: c.close()"
            )
            child = subprocess.run(
                [sys.executable, "-c", child_code, str(path)],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            self.assertEqual(child.stdout.strip(), "BUSY")
            before = path.read_bytes()
            consumer = RuntimeEvidenceConsumer(path, sink_id="fixture-ledger")
            with self.assertRaises(ConsumerError) as raised:
                consumer.consume_outbox_event(self.outbox, seq=1)
            self.assertEqual(raised.exception.code, "database_permissions_invalid")
            self.assertEqual(path.read_bytes(), before)
        finally:
            holder.rollback()
            holder.close()

    def test_manual_ledger_purge_orders_receipts_before_expired_events(self):
        import scripts.runtime_evidence_consumer as consumer_module

        self._consume()
        now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        cutoff = now - timedelta(days=consumer_module.LEDGER_RETENTION_DAYS)
        cutoff_text = cutoff.isoformat(timespec="microseconds").replace("+00:00", "Z")
        expired_text = (cutoff - timedelta(microseconds=1)).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")

        boundary_event = _event("b")
        boundary_bytes = canonical_json(boundary_event)
        boundary_record_hash = "sha256:" + hashlib.sha256(boundary_bytes).hexdigest()
        conflict = dict(self.event)
        conflict["observed_at"] = "2026-10-20T12:00:02Z"
        conflict.pop("payload_hash")
        conflict = seal_event(conflict)
        conflict_bytes = canonical_json(conflict)
        candidate_hash = hashlib.sha256(conflict_bytes).hexdigest()
        with sqlite3.connect(self.ledger) as conn:
            conn.execute(
                "UPDATE runtime_events SET committed_at=? WHERE event_ref=?",
                (expired_text, self.event["event_ref"]),
            )
            conn.execute(
                "INSERT INTO runtime_events "
                "(event_ref, payload_hash, schema_version, envelope_json, record_hash, committed_at) "
                "VALUES (?, ?, 2, ?, ?, ?)",
                (
                    boundary_event["event_ref"],
                    boundary_event["payload_hash"],
                    boundary_bytes,
                    boundary_record_hash,
                    cutoff_text,
                ),
            )
            conn.execute(
                "INSERT INTO runtime_event_conflicts "
                "(event_ref, payload_hash, schema_version, candidate_sha256, envelope_json, recorded_at) "
                "VALUES (?, ?, 2, ?, ?, ?)",
                (
                    conflict["event_ref"],
                    conflict["payload_hash"],
                    candidate_hash,
                    conflict_bytes,
                    expired_text,
                ),
            )

        first = purge_expired_runtime_evidence_ledger(self.ledger, now=now, max_rows=1)
        self.assertEqual(first.cutoff, cutoff_text)
        self.assertEqual(first.receipts_deleted, 1)
        self.assertEqual(first.events_deleted, 0)
        self.assertTrue(first.has_more)

        second = purge_expired_runtime_evidence_ledger(self.ledger, now=now, max_rows=1)
        self.assertEqual(second.events_deleted, 1)
        self.assertEqual(second.receipts_deleted, 0)
        self.assertTrue(second.has_more)

        third = purge_expired_runtime_evidence_ledger(self.ledger, now=now, max_rows=1)
        self.assertEqual(third.conflicts_deleted, 1)
        self.assertFalse(third.has_more)
        with sqlite3.connect(self.ledger) as conn:
            rows = conn.execute(
                "SELECT event_ref, committed_at FROM runtime_events"
            ).fetchall()
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM runtime_event_conflicts").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0],
                0,
            )
        self.assertEqual(rows, [(boundary_event["event_ref"], cutoff_text)])

    def test_manual_ledger_purge_rejects_bad_timestamp_and_preserves_rows(self):
        self._consume()
        with sqlite3.connect(self.ledger) as conn:
            conn.execute(
                "UPDATE runtime_events SET committed_at=? WHERE event_ref=?",
                ("0000-invalid", self.event["event_ref"]),
            )

        with self.assertRaises(ConsumerError) as raised:
            purge_expired_runtime_evidence_ledger(
                self.ledger, now=datetime(2026, 10, 21, tzinfo=timezone.utc)
            )

        self.assertEqual(raised.exception.code, "ledger_timestamp_invalid")
        with sqlite3.connect(self.ledger) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0], 1
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM transport_receipts").fetchone()[0], 1
            )

    def test_manual_ledger_purge_rejects_orphan_receipt_without_mutation(self):
        path = self.root / "orphan-receipt-ledger.sqlite3"
        initialize_runtime_evidence_ledger(path)
        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT INTO transport_receipts "
                "(event_ref, payload_hash, schema_version, sink_id, receipt_json) "
                "VALUES (?, ?, 2, ?, ?)",
                ("hmac-sha256:v1:" + "a" * 64, "sha256:" + "b" * 64, "sink", b"{}"),
            )
        before = path.read_bytes()

        with self.assertRaises(ConsumerError) as raised:
            purge_expired_runtime_evidence_ledger(
                path, now=datetime(2026, 10, 21, tzinfo=timezone.utc)
            )

        self.assertEqual(raised.exception.code, "ledger_receipt_orphaned")
        self.assertEqual(path.read_bytes(), before)

    def test_manual_ledger_purge_requires_existing_db_and_bounded_limit(self):
        path = self.root / "missing-ledger.sqlite3"
        now = datetime(2026, 10, 21, tzinfo=timezone.utc)

        with self.assertRaises(ConsumerError) as missing:
            purge_expired_runtime_evidence_ledger(path, now=now)
        self.assertEqual(missing.exception.code, "database_unavailable")
        self.assertFalse(path.exists())

        with self.assertRaises(ConsumerError) as unbounded:
            purge_expired_runtime_evidence_ledger(path, now=now, max_rows=901)
        self.assertEqual(unbounded.exception.code, "ledger_purge_limit_invalid")
        self.assertFalse(path.exists())

    @unittest.skipUnless(sys.platform == "darwin", "macOS file ownership boundary")
    def test_database_file_owned_by_another_uid_is_rejected_for_both_openers(self):
        import scripts.runtime_evidence_consumer as consumer_module

        path = self.root / "foreign-owner-ledger.sqlite3"
        initialize_runtime_evidence_ledger(path)

        writer = consumer_module._connect_writer(path, create=False)
        writer.close()
        reader = consumer_module._connect_readonly(path)
        self.assertEqual(reader.execute("PRAGMA user_version").fetchone(), (1,))
        reader.close()

        original_lstat = Path.lstat

        def lstat_as_foreign_owner(candidate):
            info = original_lstat(candidate)
            if candidate == path:
                values = list(info)
                values[4] = os.geteuid() + 1
                return os.stat_result(values)
            return info

        before = path.read_bytes()
        with patch.object(Path, "lstat", new=lstat_as_foreign_owner):
            for read_only in (False, True):
                with self.subTest(read_only=read_only):
                    with self.assertRaises(ConsumerError) as raised:
                        if read_only:
                            consumer_module._connect_readonly(path)
                        else:
                            consumer_module._connect_writer(path, create=False)
                    self.assertEqual(
                        raised.exception.code, "database_permissions_invalid"
                    )
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
