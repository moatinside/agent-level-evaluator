"""Fixture-only regression tests for Runtime Evidence Envelope V2."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from scripts.runtime_evidence_contract import (
    MAX_ENVELOPE_BYTES,
    SCHEMA,
    canonical_json,
    seal_event,
    structural_disposition,
    validate_event,
)


def REF(char: str) -> str:
    return "hmac-sha256:v1:" + char * 64


def HASH(char: str) -> str:
    return "sha256:" + char * 64


def ordinary_event() -> dict:
    event = {
        "schema_version": 2,
        "event_type": "turn_settled",
        "event_ref": REF("a"),
        "observed_at": "2026-10-20T12:00:00Z",
        "provenance": {
            "trigger_origin": "hermes_gateway",
            "source_class": "ordinary_runtime",
            "task_class": "ordinary_task",
            "classification_basis": "gateway_dispatch",
            "platform": "discord",
            "profile_ref": REF("b"),
            "session_ref": REF("c"),
            "episode_ref": REF("d"),
            "scope_ref": REF("e"),
        },
        "execution": {
            "execution_mode": "shadow",
            "terminal_status": "completed",
            "started_at": "2026-10-20T11:59:59Z",
            "ended_at": "2026-10-20T12:00:00Z",
            "persistence_status": "confirmed",
            "persistence_receipt_ref": REF("f"),
            "delivery_status": "delivered",
            "runtime_build_id": HASH("1"),
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
    return seal_event(event)


class RuntimeEvidenceContractTests(unittest.TestCase):
    def test_synthetic_ordinary_event_is_transport_only(self):
        event = ordinary_event()
        self.assertEqual(validate_event(event), ())
        self.assertEqual(structural_disposition(event), "structurally_transport_only")

    def test_structural_hmac_shape_does_not_claim_authentication(self):
        # Repeated-character refs are synthetic and have no associated key.
        # Passing proves structural acceptance only, not HMAC or source validity.
        event = ordinary_event()
        self.assertEqual(validate_event(event), ())
        self.assertEqual(structural_disposition(event), "structurally_transport_only")

    def test_configuration_ids_must_remain_null_until_manifest_allowlist_is_approved(self):
        for field in ("agent_configuration_id", "capture_configuration_id"):
            with self.subTest(field=field):
                event = ordinary_event()
                event["execution"][field] = HASH("9")
                issues = validate_event(seal_event(event))
                self.assertIn("wrong_type", issues)
                self.assertNotIn(HASH("9"), repr(issues))

    def test_schema_is_recursive_allowlist(self):
        def visit(node):
            if not isinstance(node, dict):
                return
            if node.get("type") == "object":
                self.assertIs(node.get("additionalProperties"), False)
                for child in node.get("properties", {}).values():
                    visit(child)
        visit(SCHEMA)
        self.assertNotIn("level", SCHEMA["properties"])
        self.assertNotIn("capability_id", SCHEMA["properties"])
        self.assertNotIn("semantic_verdict", SCHEMA["properties"])

    def test_rejects_unknown_nested_and_raw_content_keys_without_echoing_values(self):
        marker = "synthetic-private-marker"
        event = ordinary_event()
        event["trace"]["debug_text"] = marker
        issues = validate_event(seal_event(event))
        self.assertIn("unknown_field", issues)
        self.assertNotIn(marker, repr(issues))

        event = ordinary_event()
        event["assistant_response"] = marker
        issues = validate_event(seal_event(event))
        self.assertIn("unknown_field", issues)
        self.assertNotIn(marker, repr(issues))

    def test_rejects_level_capability_decision_and_semantic_verdict(self):
        for field in ("level", "capability_id", "decision", "semantic_verdict"):
            with self.subTest(field=field):
                event = ordinary_event()
                event[field] = "synthetic"
                self.assertIn("unknown_field", validate_event(seal_event(event)))

    def test_rejects_unkeyed_raw_identifier_hash_reference(self):
        event = ordinary_event()
        event["provenance"]["session_ref"] = HASH("4")
        issues = validate_event(seal_event(event))
        self.assertIn("invalid_format", issues)

    def test_detects_payload_tampering(self):
        event = ordinary_event()
        event["trace"]["tool_call_count"] = 4
        self.assertIn("payload_hash_mismatch", validate_event(event))

    def test_unknown_or_nonordinary_source_is_excluded(self):
        event = ordinary_event()
        event["provenance"]["task_class"] = "command"
        event["assessment"]["evaluation_eligibility"] = "excluded"
        event = seal_event(event)
        self.assertEqual(validate_event(event), ())
        self.assertEqual(structural_disposition(event), "structurally_excluded")

        event["assessment"]["evaluation_eligibility"] = "transport_only"
        self.assertIn("eligibility_mismatch", validate_event(seal_event(event)))

    def test_missing_scope_is_excluded_not_promoted(self):
        event = ordinary_event()
        event["provenance"]["scope_ref"] = None
        event["assessment"]["evaluation_eligibility"] = "excluded"
        event = seal_event(event)
        self.assertEqual(validate_event(event), ())
        self.assertEqual(structural_disposition(event), "structurally_excluded")

    def test_persistence_receipt_is_conditional(self):
        event = ordinary_event()
        event["execution"]["persistence_receipt_ref"] = None
        self.assertIn("persistence_receipt_required", validate_event(seal_event(event)))

        event["execution"]["persistence_status"] = "unconfirmed"
        event["execution"]["persistence_receipt_ref"] = REF("f")
        self.assertIn("persistence_receipt_unexpected", validate_event(seal_event(event)))

    def test_unconfirmed_persistence_is_captured_as_excluded(self):
        event = ordinary_event()
        event["execution"]["persistence_status"] = "unconfirmed"
        event["execution"]["persistence_receipt_ref"] = None
        event["assessment"]["evaluation_eligibility"] = "excluded"
        event = seal_event(event)
        self.assertEqual(validate_event(event), ())
        self.assertEqual(structural_disposition(event), "structurally_excluded")

        event["assessment"]["evaluation_eligibility"] = "transport_only"
        self.assertIn("eligibility_mismatch", validate_event(seal_event(event)))

    def test_rejects_complete_measurement_or_downstream_transport_claim(self):
        event = ordinary_event()
        event["assessment"]["measurement_status"] = "complete"
        self.assertIn("invalid_value", validate_event(seal_event(event)))

        event = ordinary_event()
        event["assessment"]["transport_status"] = "consumer_acknowledged"
        self.assertIn("invalid_value", validate_event(seal_event(event)))

    def test_schema_timestamp_pattern_enforces_calendar_and_utc(self):
        pattern = SCHEMA["properties"]["observed_at"]["pattern"]
        started = SCHEMA["properties"]["execution"]["properties"]["started_at"]["pattern"]
        ended = SCHEMA["properties"]["execution"]["properties"]["ended_at"]["pattern"]
        self.assertEqual({pattern, started, ended}, {pattern})

        cases = {
            "2026-10-20T12:00:00Z": True,
            "2026-10-20T12:00:00.123Z": True,
            r"2026-10-20T12:00:00\q1Z": False,
            "2024-02-29T23:59:59Z": True,
            "2000-02-29T00:00:00Z": True,
            "0004-02-29T00:00:00Z": True,
            "1900-02-29T00:00:00Z": False,
            "2100-02-29T00:00:00Z": False,
            "2023-02-29T00:00:00Z": False,
            "2026-04-31T00:00:00Z": False,
            "0000-01-01T00:00:00Z": False,
            "2026-10-20T12:00:00+09:00": False,
            "2026-10-20 12:00:00Z": False,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(bool(re.fullmatch(pattern, value)), expected)

    def test_local_timestamp_parser_accepts_fraction_and_rejects_bad_suffix(self):
        event = ordinary_event()
        event["observed_at"] = "2026-10-20T12:00:00.123Z"
        self.assertEqual(validate_event(seal_event(event)), ())

        event = ordinary_event()
        event["observed_at"] = r"2026-10-20T12:00:00\q1Z"
        issues = validate_event(seal_event(event))
        self.assertIn("invalid_timestamp", issues)

    def test_rejects_bad_time_order_and_non_utc_timestamps(self):
        event = ordinary_event()
        event["execution"]["started_at"] = "2026-10-20T12:00:01Z"
        self.assertIn("timestamp_order_invalid", validate_event(seal_event(event)))

        event = ordinary_event()
        event["observed_at"] = "2026-10-20T12:00:00+09:00"
        self.assertIn("invalid_timestamp", validate_event(seal_event(event)))

        event = ordinary_event()
        event["observed_at"] = "2026-10-20 12:00:00Z"
        self.assertIn("invalid_format", validate_event(seal_event(event)))

        event = ordinary_event()
        event["observed_at"] = "2026-02-30T12:00:00Z"
        self.assertIn("invalid_timestamp", validate_event(seal_event(event)))

    def test_counters_are_nonnegative_integers_and_bounded(self):
        event = ordinary_event()
        event["trace"]["tool_call_count"] = True
        self.assertIn("wrong_type", validate_event(seal_event(event)))

        event["trace"]["tool_call_count"] = 100001
        self.assertIn("limit_exceeded", validate_event(seal_event(event)))

    def test_deeply_nested_json_input_returns_bounded_error(self):
        nested = []
        cursor = nested
        for _ in range(1200):
            child = []
            cursor.append(child)
            cursor = child
        self.assertEqual(validate_event({"unknown": nested}), ("not_json_value",))

    def test_large_input_is_rejected_before_full_serialization(self):
        event = ordinary_event()
        event["synthetic_padding"] = "x" * 1_000_000
        self.assertEqual(validate_event(event), ("event_too_large",))

    def test_seal_event_rejects_oversized_input(self):
        event = ordinary_event()
        event["synthetic_padding"] = "x" * 1_000_000
        with self.assertRaisesRegex(ValueError, "^event_too_large$"):
            seal_event(event)

    def test_seal_event_rejects_final_envelope_over_limit(self):
        event = ordinary_event()
        event.pop("payload_hash")
        event["synthetic_padding"] = ""
        event["synthetic_padding"] = "x" * (
            MAX_ENVELOPE_BYTES - len(canonical_json(event))
        )
        self.assertEqual(len(canonical_json(event)), MAX_ENVELOPE_BYTES)
        with self.assertRaisesRegex(ValueError, "^event_too_large$"):
            seal_event(event)

    def test_seal_event_rejects_deep_input_without_recursion_error(self):
        nested = []
        cursor = nested
        for _ in range(1200):
            child = []
            cursor.append(child)
            cursor = child
        with self.assertRaisesRegex(ValueError, "^not_json_value$"):
            seal_event({"nested": nested})

    def test_oversized_envelope_is_rejected(self):
        event = ordinary_event()
        event["synthetic_padding"] = "x" * 9000
        issues = validate_event(event)
        self.assertEqual(issues, ("event_too_large",))

    def test_v1_gateway_record_is_rejected_not_migrated(self):
        legacy = {
            "schema_version": 1,
            "evidence_origin": "hermes_gateway",
            "level": 5,
            "capability_id": "self_reflection",
        }
        self.assertEqual(structural_disposition(legacy), "rejected")
        self.assertIn("missing_required", validate_event(legacy))

    def test_schema_file_is_valid_json(self):
        path = Path(__file__).resolve().parents[1] / "schemas" / "runtime-evidence-envelope-v2.schema.json"
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded, SCHEMA)


if __name__ == "__main__":
    unittest.main()
