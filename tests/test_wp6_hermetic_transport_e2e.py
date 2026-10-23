"""WP6 hermetic transport E2E: Hermes Outbox -> Evaluator consumer -> ledger -> ACK -> report.

Fixture-only. Every database lives in a TemporaryDirectory; no Gateway runner,
SessionDB, Gateway API, R2, Keychain, or runtime root is touched. The Hermes
Outbox module is loaded read-only from its candidate worktree and the suite is
skipped when that worktree is absent.
"""

from __future__ import annotations

import copy
import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.runtime_evidence_consumer import (
    ConsumerError,
    RuntimeEvidenceConsumer,
    initialize_runtime_evidence_ledger,
)
from scripts.runtime_evidence_contract import canonical_json, seal_event, validate_event
from scripts.runtime_evidence_transport_report import build_runtime_evidence_transport_report


SINK_ID = "fixture-ledger"
HERMES_WORKTREE = Path(
    os.environ.get(
        "WP6_HERMES_WORKTREE",
        str(Path.home() / "Developer" / "hermes-worktrees" / "runtime-evidence-wp2"),
    )
)
OUTBOX_MODULE_PATH = HERMES_WORKTREE / "gateway" / "runtime_evidence_outbox.py"
_FIXED_CLOCK = lambda: datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)  # noqa: E731


def _load_outbox_module(hermes_home: str):
    # The module reads no configuration, but HERMES_HOME is isolated anyway so an
    # accidental import side effect cannot reach the user's profile.
    with patch.dict(os.environ, {"HERMES_HOME": hermes_home}):
        spec = importlib.util.spec_from_file_location("wp6_runtime_evidence_outbox", OUTBOX_MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        previous_dont_write = sys.dont_write_bytecode
        # Read-only use of the Hermes worktree: do not drop .pyc files into it.
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(spec.name, None)
            raise
        finally:
            sys.dont_write_bytecode = previous_dont_write
    return module


def _ref(char: str) -> str:
    return "hmac-sha256:v1:" + char * 64


def _event(ref_char: str = "a", *, persistence: str = "confirmed", tool_calls: int = 2) -> dict:
    confirmed = persistence == "confirmed"
    body = {
        "schema_version": 2,
        "event_type": "turn_settled",
        "event_ref": _ref(ref_char),
        "observed_at": "2026-10-23T12:00:00Z",
        "provenance": {
            "trigger_origin": "hermes_gateway",
            "source_class": "ordinary_runtime",
            "task_class": "ordinary_task",
            "classification_basis": "gateway_dispatch",
            "platform": "discord",
            "profile_ref": _ref("b"),
            "session_ref": _ref("c"),
            "episode_ref": _ref("d"),
            "scope_ref": _ref("e"),
        },
        "execution": {
            "execution_mode": "shadow",
            "terminal_status": "completed",
            "started_at": "2026-10-23T11:59:59Z",
            "ended_at": "2026-10-23T12:00:00Z",
            "persistence_status": persistence,
            "persistence_receipt_ref": _ref("f") if confirmed else None,
            "delivery_status": "delivered",
            "runtime_build_id": "sha256:" + "1" * 64,
            "agent_configuration_id": None,
            "capture_configuration_id": None,
        },
        "trace": {
            "turn_count": 1,
            "tool_call_count": tool_calls,
            "tool_error_count": 0,
            "correction_count": 0,
            "evidence_reference_count": 1,
            "iteration_count": 2,
        },
        "assessment": {
            "transport_status": "captured",
            "measurement_status": "not_assessed",
            "evaluation_eligibility": "transport_only" if confirmed else "excluded",
        },
    }
    return seal_event(body)


@unittest.skipUnless(OUTBOX_MODULE_PATH.is_file(), "Hermes runtime-evidence Outbox candidate worktree is absent")
class WP6HermeticTransportE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.outbox_mod = _load_outbox_module(str(self.root / "hermes-home"))
        self.outbox_path = self.root / "outbox.sqlite3"
        self.ledger_path = self.root / "ledger.sqlite3"
        self.outbox_mod.initialize_runtime_evidence_outbox(self.outbox_path)
        initialize_runtime_evidence_ledger(self.ledger_path)
        self.outbox = self.outbox_mod.DurableRuntimeEvidenceOutbox(
            self.outbox_path, validator=validate_event, clock=_FIXED_CLOCK
        )
        self.consumer = RuntimeEvidenceConsumer(self.ledger_path, sink_id=SINK_ID, clock=_FIXED_CLOCK)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _report(self) -> dict:
        return build_runtime_evidence_transport_report(
            self.outbox_path, self.ledger_path, sink_id=SINK_ID, max_records=100
        )

    def _assert_unmeasured_denominators(self, report: dict) -> None:
        self.assertIsNone(report["counts"]["emitted"])
        self.assertEqual(
            report["unavailable_count_reasons"]["emitted"],
            "independent_capture_denominator_not_implemented",
        )
        self.assertIsNone(report["counts"]["evaluation_eligible"])
        self.assertIsNone(report["outcome_counts"]["duplicate"])
        self.assertFalse(report["claims"]["promotion_input"])
        self.assertFalse(report["claims"]["legacy_evidence_included"])

    def _row_count(self, path: Path, table: str) -> int:
        with sqlite3.connect(path) as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_completed_turn_flows_outbox_to_ack_and_exact_report_readback(self):
        enqueued = self.outbox.enqueue(_event("a"))
        self.assertEqual(enqueued.status, "persisted")
        acked = self.consumer.consume_outbox_event(self.outbox_path, seq=enqueued.seq)
        self.assertEqual(acked.status, "acknowledged")
        self.assertEqual(acked.receipt["readback_status"], "exact_match")

        report = self._report()
        counts = report["counts"]
        self.assertEqual(report["report_status"], "partial")
        self.assertEqual(counts["outbox_persisted"], 1)
        self.assertEqual(counts["ledger_persisted"], 1)
        self.assertEqual(counts["consumer_acknowledged"], 1)
        self.assertEqual(counts["outbox_to_ledger_exact"], 1)
        self.assertEqual(counts["report_visible"], 1)
        self.assertEqual(counts["structurally_transport_only"], 1)
        self.assertEqual(counts["structurally_excluded"], 0)
        self._assert_unmeasured_denominators(report)

    def test_persistence_unconfirmed_is_transported_but_structurally_excluded(self):
        event = _event("a", persistence="unconfirmed")
        enqueued = self.outbox.enqueue(event)
        self.consumer.consume_outbox_event(self.outbox_path, seq=enqueued.seq)

        report = self._report()
        self.assertEqual(report["counts"]["consumer_acknowledged"], 1)
        self.assertEqual(report["counts"]["structurally_excluded"], 1)
        self.assertEqual(report["counts"]["structurally_transport_only"], 0)
        self._assert_unmeasured_denominators(report)

        # Claiming eligibility without a confirmed receipt is a contract violation
        # and never reaches the Outbox.
        forged = copy.deepcopy(event)
        forged["event_ref"] = _ref("9")
        forged["assessment"]["evaluation_eligibility"] = "transport_only"
        forged.pop("payload_hash")
        with self.assertRaises(self.outbox_mod.OutboxError) as raised:
            self.outbox.enqueue(seal_event(forged))
        self.assertEqual(raised.exception.code, "event_rejected")
        self.assertEqual(self._row_count(self.outbox_path, "outbox_events"), 1)

    def test_malformed_and_nested_forbidden_keys_are_rejected_before_outbox(self):
        nested = _event("a")
        nested.pop("payload_hash")
        nested["trace"]["raw_message_text"] = "must-not-persist"
        top_level = _event("b")
        top_level.pop("payload_hash")
        top_level["level"] = 5
        malformed = _event("c")
        malformed["trace"] = "not-an-object"

        for candidate in (seal_event(nested), seal_event(top_level), malformed):
            with self.subTest(keys=sorted(candidate)):
                with self.assertRaises(self.outbox_mod.OutboxError) as raised:
                    self.outbox.enqueue(candidate)
                self.assertEqual(raised.exception.code, "event_rejected")
        self.assertEqual(self._row_count(self.outbox_path, "outbox_events"), 0)
        self.assertNotIn(b"must-not-persist", self.outbox_path.read_bytes())
        self.assertEqual(self._report()["counts"]["outbox_persisted"], 0)

    def test_legacy_v1_gateway_record_never_enters_outbox_or_report(self):
        legacy = {
            "schema_version": 1,
            "evidence_origin": "hermes_gateway",
            "level": 5,
            "capability_id": "self_reflection",
        }
        with self.assertRaises(self.outbox_mod.OutboxError) as raised:
            self.outbox.enqueue(legacy)
        self.assertEqual(raised.exception.code, "event_rejected")
        report = self._report()
        self.assertEqual(report["counts"]["outbox_persisted"], 0)
        self.assertEqual(report["counts"]["report_visible"], 0)
        self._assert_unmeasured_denominators(report)

    def test_outbox_unavailable_fails_closed_and_recovers_after_bootstrap(self):
        missing = self.root / "not-bootstrapped.sqlite3"
        outbox = self.outbox_mod.DurableRuntimeEvidenceOutbox(missing, validator=validate_event, clock=_FIXED_CLOCK)
        with self.assertRaises(self.outbox_mod.OutboxError):
            outbox.enqueue(_event("a"))
        self.assertFalse(missing.exists())

        # The unavailable Outbox leaves no trace, so the report cannot infer the
        # lost turn: emitted stays null instead of collapsing to zero.
        report = self._report()
        self.assertEqual(report["counts"]["outbox_persisted"], 0)
        self._assert_unmeasured_denominators(report)

        self.outbox_mod.initialize_runtime_evidence_outbox(missing)
        self.assertEqual(outbox.enqueue(_event("a")).status, "persisted")

    def test_consumer_unavailable_withholds_ack_then_retry_acknowledges(self):
        enqueued = self.outbox.enqueue(_event("a"))
        late_ledger = self.root / "late-ledger.sqlite3"
        consumer = RuntimeEvidenceConsumer(late_ledger, sink_id=SINK_ID, clock=_FIXED_CLOCK)
        with self.assertRaises(ConsumerError):
            consumer.consume_outbox_event(self.outbox_path, seq=enqueued.seq)
        self.assertFalse(late_ledger.exists())

        initialize_runtime_evidence_ledger(late_ledger)
        pending = build_runtime_evidence_transport_report(
            self.outbox_path, late_ledger, sink_id=SINK_ID, max_records=100
        )
        self.assertEqual(pending["counts"]["outbox_pending_without_ledger"], 1)
        self.assertEqual(pending["counts"]["consumer_acknowledged"], 0)

        self.assertEqual(consumer.consume_outbox_event(self.outbox_path, seq=enqueued.seq).status, "acknowledged")
        recovered = build_runtime_evidence_transport_report(
            self.outbox_path, late_ledger, sink_id=SINK_ID, max_records=100
        )
        self.assertEqual(recovered["counts"]["outbox_pending_without_ledger"], 0)
        self.assertEqual(recovered["counts"]["consumer_acknowledged"], 1)

    def test_failure_after_ledger_commit_before_ack_retries_idempotently(self):
        enqueued = self.outbox.enqueue(_event("a"))
        with patch("scripts.runtime_evidence_consumer._read_ledger_event", return_value=None):
            with self.assertRaises(ConsumerError) as raised:
                self.consumer.consume_outbox_event(self.outbox_path, seq=enqueued.seq)
        self.assertEqual(raised.exception.code, "ledger_readback_mismatch")

        interrupted = self._report()
        self.assertEqual(interrupted["counts"]["ledger_persisted"], 1)
        self.assertEqual(interrupted["counts"]["consumer_acknowledged"], 0)

        retry = self.consumer.consume_outbox_event(self.outbox_path, seq=enqueued.seq)
        self.assertEqual(retry.status, "acknowledged")
        self.assertEqual(retry.receipt["disposition"], "duplicate")
        self.assertEqual(self._row_count(self.ledger_path, "runtime_events"), 1)
        self.assertEqual(self._row_count(self.ledger_path, "transport_receipts"), 1)
        self.assertEqual(self._report()["counts"]["consumer_acknowledged"], 1)

    def test_duplicate_event_is_idempotent_across_both_boundaries(self):
        event = _event("a")
        first = self.outbox.enqueue(event)
        second = self.outbox.enqueue(copy.deepcopy(event))
        self.assertEqual((first.status, second.status), ("persisted", "duplicate"))
        self.assertEqual(first.seq, second.seq)

        ack1 = self.consumer.consume_outbox_event(self.outbox_path, seq=first.seq)
        ack2 = self.consumer.consume_outbox_event(self.outbox_path, seq=second.seq)
        self.assertEqual(ack1.receipt, ack2.receipt)
        self.assertEqual(self._row_count(self.outbox_path, "outbox_events"), 1)
        self.assertEqual(self._row_count(self.ledger_path, "runtime_events"), 1)
        self.assertEqual(self._row_count(self.ledger_path, "transport_receipts"), 1)

        report = self._report()
        self.assertEqual(report["counts"]["consumer_acknowledged"], 1)
        # Duplicate occurrences are absorbed, not durably counted.
        self.assertIsNone(report["outcome_counts"]["duplicate"])

    def test_same_event_ref_different_payload_is_conflict_and_never_overwrites(self):
        original = _event("a", tool_calls=2)
        variant = _event("a", tool_calls=3)
        first = self.outbox.enqueue(original)
        self.consumer.consume_outbox_event(self.outbox_path, seq=first.seq)
        self.assertEqual(self.outbox.enqueue(variant).status, "conflict")

        report = self._report()
        self.assertEqual(report["outcome_counts"]["conflict"]["outbox_conflict_rows"], 1)
        self.assertEqual(report["counts"]["consumer_acknowledged"], 1)
        with sqlite3.connect(self.outbox_path) as conn:
            stored_hash = conn.execute("SELECT payload_hash FROM outbox_events").fetchone()[0]
        self.assertEqual(stored_hash, original["payload_hash"])

    def test_report_does_not_count_ack_when_receipt_is_missing(self):
        enqueued = self.outbox.enqueue(_event("a"))
        self.consumer.consume_outbox_event(self.outbox_path, seq=enqueued.seq)
        with sqlite3.connect(self.ledger_path) as conn:
            conn.execute("DELETE FROM transport_receipts")

        report = self._report()
        self.assertEqual(report["counts"]["ledger_persisted"], 1)
        self.assertEqual(report["counts"]["consumer_acknowledged"], 0)
        self.assertEqual(report["outcome_counts"]["accepted"], 0)

    def test_report_does_not_count_ack_when_ledger_row_is_stale(self):
        enqueued = self.outbox.enqueue(_event("a"))
        self.consumer.consume_outbox_event(self.outbox_path, seq=enqueued.seq)
        stale = _event("a", tool_calls=9)
        with sqlite3.connect(self.ledger_path) as conn:
            conn.execute(
                "UPDATE runtime_events SET envelope_json=?",
                (canonical_json(stale),),
            )

        report = self._report()
        self.assertEqual(report["report_status"], "incomplete")
        self.assertEqual(report["counts"]["consumer_acknowledged"], 0)
        self.assertEqual(report["anomaly_counts"]["invalid_ledger_rows"], 1)
        self.assertEqual(report["anomaly_counts"]["receipts_without_exact_ledger_row"], 1)


if __name__ == "__main__":
    unittest.main()
