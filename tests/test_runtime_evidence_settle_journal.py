from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.runtime_evidence_consumer import RuntimeEvidenceConsumer, initialize_runtime_evidence_ledger
from scripts.runtime_evidence_settle_journal import (
    SettleJournalError,
    load_settle_journal_snapshot,
    validate_settle_marker,
)
from scripts.runtime_evidence_transport_report import (
    build_runtime_evidence_transport_report,
    main as report_main,
)
from tests.test_runtime_evidence_transport_report import SINK_ID, _create_outbox, _event


def _marker(digit: str, outcome: str = "persisted") -> dict:
    body = {
        "schema": "agent-level/runtime-evidence/settle-marker/v1",
        "event_ref": "hmac-sha256:v1:" + digit * 64,
        "settled_at": "2026-10-23T00:00:00Z",
        "terminal_status": "completed",
        "outbox_outcome": outcome,
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    body["marker_hash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return body


class SettleJournalReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.outbox = self.root / "outbox.sqlite3"
        self.ledger = self.root / "ledger.sqlite3"
        # Outbox holds turns "a" and "b"; the journal will hold "a" and "c".
        _create_outbox(self.outbox, [_event("a"), _event("b")])
        initialize_runtime_evidence_ledger(self.ledger)
        RuntimeEvidenceConsumer(self.ledger, sink_id=SINK_ID).consume_outbox_event(self.outbox, seq=1)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _snapshot(self, markers: list[dict], name: str = "snapshot.jsonl") -> Path:
        path = self.root / name
        path.write_text("".join(json.dumps(m, sort_keys=True) + "\n" for m in markers), encoding="utf-8")
        return path

    def test_emitted_stays_null_without_snapshot(self):
        report = build_runtime_evidence_transport_report(self.outbox, self.ledger, sink_id=SINK_ID, max_records=10)
        self.assertIsNone(report["counts"]["emitted"])
        self.assertEqual(report["unavailable_count_reasons"]["emitted"], "independent_capture_denominator_not_implemented")
        self.assertNotIn("capture_reconciliation", report)

    def test_snapshot_sets_emitted_and_reconciles_both_failure_domains(self):
        markers = load_settle_journal_snapshot(self._snapshot([_marker("a"), _marker("c", "outbox_unavailable")]))
        report = build_runtime_evidence_transport_report(
            self.outbox, self.ledger, sink_id=SINK_ID, max_records=10, journal_markers=markers
        )
        recon = report["capture_reconciliation"]
        self.assertEqual(report["counts"]["emitted"], 2)
        self.assertNotIn("emitted", report["unavailable_count_reasons"])
        self.assertEqual(
            (recon["journal_and_outbox"], recon["journal_only"], recon["outbox_only"]), (1, 1, 1)
        )
        self.assertEqual(recon["journal_reported_outbox_outcomes"]["outbox_unavailable"], 1)
        self.assertEqual(recon["emitted_basis"], "r2_settle_markers_lower_bound")
        self.assertFalse(report["claims"]["promotion_input"])
        self.assertNotIn("hmac-sha256", json.dumps(report))

    def test_snapshot_fails_closed_instead_of_counting_zero(self):
        cases = {
            "journal_snapshot_line_invalid": [dict(_marker("a"), terminal_status="failed")],
            "journal_snapshot_conflict": [_marker("a"), dict(_marker("a", "conflict"))],
        }
        for code, markers in cases.items():
            with self.subTest(code=code):
                with self.assertRaises(SettleJournalError) as ctx:
                    load_settle_journal_snapshot(self._snapshot(markers, f"{code}.jsonl"))
                self.assertEqual(ctx.exception.code, code)
        with self.assertRaises(SettleJournalError) as ctx:
            load_settle_journal_snapshot(self.root / "missing.jsonl")
        self.assertEqual(ctx.exception.code, "journal_snapshot_unavailable")
        with self.assertRaises(SettleJournalError) as ctx:
            load_settle_journal_snapshot("relative.jsonl")
        self.assertEqual(ctx.exception.code, "journal_snapshot_path_invalid")

    def test_identical_duplicate_lines_count_once(self):
        markers = load_settle_journal_snapshot(self._snapshot([_marker("a"), _marker("a")]))
        self.assertEqual(len(markers), 1)

    def test_marker_contract_rejects_extra_keys_and_raw_refs(self):
        self.assertEqual(validate_settle_marker(dict(_marker("a"), text="x")), ("marker_keys",))
        raw = dict(_marker("a"), event_ref="discord:1234")
        self.assertIn("marker_event_ref", validate_settle_marker(raw))

    def test_cli_accepts_explicit_snapshot_and_reports_error_codes_only(self):
        snapshot = self._snapshot([_marker("a")])
        out = StringIO()
        with redirect_stdout(out):
            code = report_main(["--outbox-db", str(self.outbox), "--ledger-db", str(self.ledger),
                                "--sink-id", SINK_ID, "--max-records", "10", "--journal-snapshot", str(snapshot)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["counts"]["emitted"], 1)
        out = StringIO()
        with redirect_stdout(out):
            code = report_main(["--outbox-db", str(self.outbox), "--ledger-db", str(self.ledger),
                                "--sink-id", SINK_ID, "--max-records", "10",
                                "--journal-snapshot", str(self.root / "missing.jsonl")])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue()), {"status": "error", "error_code": "journal_snapshot_unavailable"})


if __name__ == "__main__":
    unittest.main()
