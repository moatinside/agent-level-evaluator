from __future__ import annotations

import hashlib
import inspect
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import fields, replace
from pathlib import Path
from typing import Sequence, Tuple, cast

from scripts.wp5_episode_assembler import (
    AdmissionEvidence,
    ReadOnlyFixtureResolver,
    ResolvedEvent,
    Resolution,
    assemble_episode,
    build_blind_calibration_packet,
)


FIXTURE_EPISODE_REF = "episode:fixture-1"
FIXTURE_PRODUCER_VERSION = "wp4-wp5-fixture-v0"
FIXTURE_CODEBOOK_VERSION = "wp5-fixture-codebook-v0"
MANIFEST_DDL = (
    "CREATE TABLE wp5_episodes ("
    "scope_ref TEXT NOT NULL, episode_ref TEXT NOT NULL, producer_version TEXT NOT NULL, "
    "codebook_version TEXT NOT NULL, status TEXT NOT NULL, expected_event_count INTEGER NOT NULL)"
)
EVENT_DDL = (
    "CREATE TABLE wp5_events ("
    "scope_ref TEXT NOT NULL, episode_ref TEXT NOT NULL, event_ref TEXT NOT NULL UNIQUE, "
    "sequence INTEGER NOT NULL, event_kind TEXT NOT NULL, actor_class TEXT NOT NULL, "
    "code TEXT NOT NULL, related_ref TEXT)"
)
BASE_ROWS = [
    ("scope:approved", FIXTURE_EPISODE_REF, "question:q0", 0, "question_initial", "user", "initial_question", None),
    ("scope:approved", FIXTURE_EPISODE_REF, "evidence:e0", 1, "evidence", "source", "supports", None),
    ("scope:approved", FIXTURE_EPISODE_REF, "question:q1", 2, "question_update", "agent", "evidence_driven", "evidence:e0"),
    ("scope:approved", FIXTURE_EPISODE_REF, "feedback:f0", 3, "feedback", "user", "acceptance", "question:q1"),
    ("scope:approved", FIXTURE_EPISODE_REF, "decision:d0", 4, "decision", "user", "on_hold", None),
    ("scope:approved", FIXTURE_EPISODE_REF, "validation:v0", 5, "next_validation", "agent", "customer_interview", None),
    ("scope:approved", FIXTURE_EPISODE_REF, "scope_topic:s0", 6, "deferred_scope", "agent", "payer", None),
]
COMPLETE_ADMISSION = AdmissionEvidence(
    capture_complete=True,
    episode_boundary_verified=True,
    single_lineage_verified=True,
    source_order_verified=True,
    inactive_history_resolved=True,
    compacted_history_resolved=True,
    pagination_complete=True,
    recovery_reconciled=True,
)


def _manifest(
    scope_ref: str = "scope:approved",
    episode_ref: str = FIXTURE_EPISODE_REF,
    status: str = "closed",
    expected_event_count: int = len(BASE_ROWS),
    producer_version: str = FIXTURE_PRODUCER_VERSION,
    codebook_version: str = FIXTURE_CODEBOOK_VERSION,
) -> Tuple[object, ...]:
    return (scope_ref, episode_ref, producer_version, codebook_version, status, expected_event_count)


def _make_store(
    directory: Path,
    rows: Sequence[Tuple[object, ...]] = BASE_ROWS,
    manifests: Sequence[Tuple[object, ...]] | None = None,
    extra_column: bool = False,
    unique_event_ref: bool = True,
) -> Path:
    path = directory / "fixture.sqlite3"
    connection = sqlite3.connect(str(path))
    try:
        event_ddl = EVENT_DDL if unique_event_ref else EVENT_DDL.replace("event_ref TEXT NOT NULL UNIQUE", "event_ref TEXT NOT NULL")
        if extra_column:
            event_ddl = event_ddl[:-1] + ", raw_transcript TEXT)"
        connection.execute(MANIFEST_DDL)
        connection.execute(event_ddl)
        if manifests is None:
            counts: dict[Tuple[object, object], int] = {}
            for row in rows:
                key = (row[0], row[1])
                counts[key] = counts.get(key, 0) + 1
            manifests = [
                _manifest(scope_ref=str(scope), episode_ref=str(episode), expected_event_count=count)
                for (scope, episode), count in counts.items()
            ]
        connection.executemany("INSERT INTO wp5_episodes VALUES (?, ?, ?, ?, ?, ?)", manifests)
        connection.executemany(
            "INSERT INTO wp5_events "
            "(scope_ref, episode_ref, event_ref, sequence, event_kind, actor_class, code, related_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.commit()
    finally:
        connection.close()
    return path


def _open_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _InMemoryEpisodeResolver:
    def __init__(self, events: Tuple[ResolvedEvent, ...]) -> None:
        self._events = events
        self.last_budget: int | None = None

    def resolve(self, scope_ref: str, episode_ref: str, max_event_refs: int) -> Resolution:
        self.last_budget = max_event_refs
        if scope_ref != "scope:approved":
            return Resolution("out_of_scope", "scope_not_approved")
        if episode_ref != FIXTURE_EPISODE_REF:
            return Resolution("not_found", "episode_manifest_not_found")
        if len(self._events) > max_event_refs:
            return Resolution("input_unavailable", "event_ref_budget_exceeded")
        return Resolution("resolved", "none", self._events, COMPLETE_ADMISSION)


class WP5EpisodeAssemblerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.path = _make_store(self.directory)
        self.connection = _open_readonly(self.path)
        self.resolver = ReadOnlyFixtureResolver(self.connection, {"scope:approved"}, max_event_refs=7)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp.cleanup()

    def test_assembles_complete_closed_episode_and_blind_packet_in_memory(self) -> None:
        before = _sha256(self.path)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            episode = assemble_episode(
                self.resolver, "scope:approved", FIXTURE_EPISODE_REF, "human-calibration-v1", max_event_refs=7
            )
            packet = build_blind_calibration_packet(episode, "case:case-1", 4096)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(episode.trajectory_status, "complete")
        self.assertEqual(episode.causal_order, "evidence_agent_update_user_judgment")
        self.assertEqual(episode.event_refs, tuple(row[2] for row in BASE_ROWS))
        self.assertEqual(episode.update_reason_codes, ("evidence_driven",))
        self.assertEqual(episode.feedback_types, ("acceptance",))
        self.assertEqual(episode.decision_statuses, ("on_hold",))
        self.assertEqual(packet.case_ref, "case:case-1")
        self.assertEqual(packet.axes, (
            "initial_question_capture",
            "evidence_driven_update",
            "question_update_rationale",
            "decision_proximity",
            "feedback_interpretation",
        ))
        field_names = {item.name for item in fields(packet)}
        self.assertEqual(field_names, {
            "case_ref", "rubric_version", "axes", "trajectory_status", "causal_order",
            "initial_question_refs", "question_update_refs", "update_reason_codes", "evidence_refs",
            "feedback_types", "decision_statuses", "next_validation_codes", "deferred_scope_codes",
        })
        rendered = json.dumps(packet.__dict__, sort_keys=True)
        for forbidden in ("human_calibration", "rationale_ref", "rater", "identity", "answered_at", "transcript", "session_id"):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual(_sha256(self.path), before)
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_resolver_keeps_manifest_and_rows_in_one_read_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as snapshot_tmp:
            path = _make_store(Path(snapshot_tmp))
            writer = sqlite3.connect(str(path))
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("SELECT count(*) FROM wp5_events").fetchone()
            reader = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(reader, {"scope:approved"}, max_event_refs=7)
                changed = False

                def update_after_manifest(statement: str) -> None:
                    nonlocal changed
                    if not changed and "FROM wp5_events" in statement:
                        writer.execute(
                            "UPDATE wp5_events SET code = 'contradicts' "
                            "WHERE event_ref = 'evidence:e0'"
                        )
                        writer.commit()
                        changed = True

                reader.set_trace_callback(update_after_manifest)
                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
                self.assertTrue(changed)
                self.assertEqual(result.status, "resolved")
                self.assertEqual(result.events[1].code, "supports")
                self.assertEqual(
                    writer.execute(
                        "SELECT code FROM wp5_events WHERE event_ref = 'evidence:e0'"
                    ).fetchone()[0],
                    "contradicts",
                )
            finally:
                reader.close()
                writer.close()

    def test_resolver_preserves_callers_existing_read_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as snapshot_tmp:
            path = _make_store(Path(snapshot_tmp))
            writer = sqlite3.connect(str(path))
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("SELECT count(*) FROM wp5_events").fetchone()
            reader = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(reader, {"scope:approved"}, max_event_refs=7)
                reader.execute("BEGIN")
                self.assertEqual(
                    reader.execute(
                        "SELECT code FROM wp5_events WHERE event_ref = 'evidence:e0'"
                    ).fetchone()[0],
                    "supports",
                )
                writer.execute(
                    "UPDATE wp5_events SET code = 'contradicts' "
                    "WHERE event_ref = 'evidence:e0'"
                )
                writer.commit()

                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
                self.assertEqual(result.status, "resolved")
                self.assertEqual(result.events[1].code, "supports")
                self.assertTrue(reader.in_transaction)
            finally:
                reader.rollback()
                reader.close()
                writer.close()

    def test_resolver_returns_every_episode_row_without_caller_selected_subset(self) -> None:
        result = self.resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(len(result.events), 7)
        self.assertEqual([event.sequence for event in result.events], list(range(7)))
        self.assertEqual([event.event_ref for event in result.events], [row[2] for row in BASE_ROWS])

    def test_assembler_accepts_source_agnostic_resolver_contract(self) -> None:
        events = tuple(ResolvedEvent(*row) for row in BASE_ROWS)
        resolver = _InMemoryEpisodeResolver(events)
        episode = assemble_episode(
            resolver, "scope:approved", FIXTURE_EPISODE_REF, "human-calibration-v1", max_event_refs=7
        )
        self.assertEqual(episode.trajectory_status, "complete")
        self.assertEqual(episode.event_refs, tuple(row[2] for row in BASE_ROWS))
        self.assertEqual(resolver.last_budget, 7)

    def test_assembler_rejects_invalid_event_budget_before_resolver_call(self) -> None:
        class NotCalledResolver:
            calls = 0

            def resolve(self, scope_ref: str, episode_ref: str, max_event_refs: int) -> Resolution:
                self.calls += 1
                return Resolution("resolved", "none", tuple(ResolvedEvent(*row) for row in BASE_ROWS))

        resolver = NotCalledResolver()
        for invalid_budget in (0, -1, True, 1.5):
            with self.subTest(invalid_budget=invalid_budget):
                with self.assertRaisesRegex(ValueError, "^invalid_event_ref_budget$"):
                    assemble_episode(
                        resolver, "scope:approved", FIXTURE_EPISODE_REF, "human-calibration-v1",
                        max_event_refs=cast(int, invalid_budget),
                    )
        self.assertEqual(resolver.calls, 0)

    def test_assembler_rejects_adapter_rows_over_explicit_event_budget(self) -> None:
        class OversizedResolver:
            last_budget: int | None = None

            def resolve(self, scope_ref: str, episode_ref: str, max_event_refs: int) -> Resolution:
                self.last_budget = max_event_refs
                return Resolution("resolved", "none", tuple(ResolvedEvent(*row) for row in BASE_ROWS))

        resolver = OversizedResolver()
        with self.assertRaisesRegex(ValueError, "^source_event_ref_budget_exceeded$"):
            assemble_episode(
                resolver, "scope:approved", FIXTURE_EPISODE_REF, "human-calibration-v1", max_event_refs=6
            )
        self.assertEqual(resolver.last_budget, 6)

    def test_unresolved_source_admission_conditions_fail_closed(self) -> None:
        reasons = (
            "capture_incomplete",
            "inactive_history_unresolved",
            "compacted_history_unresolved",
            "lineage_unresolved",
            "pagination_incomplete",
            "recovery_unreconciled",
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                class UnavailableResolver:
                    def resolve(
                        self, scope_ref: str, episode_ref: str, max_event_refs: int
                    ) -> Resolution:
                        return Resolution("input_unavailable", reason)

                with self.assertRaisesRegex(ValueError, f"^source_{reason}$"):
                    assemble_episode(
                        UnavailableResolver(), "scope:approved", FIXTURE_EPISODE_REF,
                        "human-calibration-v1", max_event_refs=7,
                    )

    def test_assembler_fails_closed_on_unavailable_source_contract_result(self) -> None:
        class UnavailableResolver:
            def resolve(self, scope_ref: str, episode_ref: str, max_event_refs: int) -> Resolution:
                return Resolution("input_unavailable", "capture_incomplete")

        with self.assertRaisesRegex(ValueError, "^source_capture_incomplete$"):
            assemble_episode(
                UnavailableResolver(), "scope:approved", FIXTURE_EPISODE_REF, "human-calibration-v1", max_event_refs=7
            )

    def test_resolved_contract_requires_admission_evidence(self) -> None:
        class MissingEvidenceResolver:
            def resolve(self, scope_ref: str, episode_ref: str, max_event_refs: int) -> Resolution:
                return Resolution("resolved", "none", tuple(ResolvedEvent(*row) for row in BASE_ROWS))

        with self.assertRaisesRegex(ValueError, "^source_admission_evidence_missing$"):
            assemble_episode(
                MissingEvidenceResolver(), "scope:approved", FIXTURE_EPISODE_REF,
                "human-calibration-v1", max_event_refs=7,
            )

    def test_resolved_contract_rejects_each_incomplete_admission_condition(self) -> None:
        fields_to_reject = (
            "capture_complete",
            "episode_boundary_verified",
            "single_lineage_verified",
            "source_order_verified",
            "inactive_history_resolved",
            "compacted_history_resolved",
            "pagination_complete",
            "recovery_reconciled",
        )
        events = tuple(ResolvedEvent(*row) for row in BASE_ROWS)
        for field in fields_to_reject:
            with self.subTest(field=field):
                class IncompleteEvidenceResolver:
                    def resolve(self, scope_ref: str, episode_ref: str, max_event_refs: int) -> Resolution:
                        evidence = replace(COMPLETE_ADMISSION, **{field: False})
                        return Resolution("resolved", "none", events, evidence)

                with self.assertRaisesRegex(ValueError, "^source_admission_incomplete$"):
                    assemble_episode(
                        IncompleteEvidenceResolver(), "scope:approved", FIXTURE_EPISODE_REF,
                        "human-calibration-v1", max_event_refs=7,
                    )

    def test_admission_evidence_requires_literal_boolean_values(self) -> None:
        events = tuple(ResolvedEvent(*row) for row in BASE_ROWS)
        invalid = replace(COMPLETE_ADMISSION, pagination_complete=cast(bool, 1))

        class InvalidEvidenceResolver:
            def resolve(self, scope_ref: str, episode_ref: str, max_event_refs: int) -> Resolution:
                return Resolution("resolved", "none", events, invalid)

        with self.assertRaisesRegex(ValueError, "^source_resolution_contract_invalid$"):
            assemble_episode(
                InvalidEvidenceResolver(), "scope:approved", FIXTURE_EPISODE_REF,
                "human-calibration-v1", max_event_refs=7,
            )

    def test_nonresolved_result_cannot_carry_admission_evidence(self) -> None:
        class ContradictoryResolver:
            def resolve(self, scope_ref: str, episode_ref: str, max_event_refs: int) -> Resolution:
                return Resolution("input_unavailable", "capture_incomplete", (), COMPLETE_ADMISSION)

        with self.assertRaisesRegex(ValueError, "^source_resolution_contract_invalid$"):
            assemble_episode(
                ContradictoryResolver(), "scope:approved", FIXTURE_EPISODE_REF,
                "human-calibration-v1", max_event_refs=7,
            )

    def test_assembler_rejects_unapproved_reason_codes_without_echo(self) -> None:
        sentinel = "rawbodysecretmarker"

        class UnapprovedReasonResolver:
            def resolve(self, scope_ref: str, episode_ref: str, max_event_refs: int) -> Resolution:
                return Resolution("input_unavailable", sentinel)

        with self.assertRaisesRegex(ValueError, "^source_resolution_contract_invalid$") as caught:
            assemble_episode(
                UnapprovedReasonResolver(), "scope:approved", FIXTURE_EPISODE_REF,
                "human-calibration-v1", max_event_refs=7,
            )
        self.assertNotIn(sentinel, str(caught.exception))

    def test_assembler_rejects_out_of_scope_rows_from_source_adapter(self) -> None:
        events = tuple(ResolvedEvent(*row) for row in BASE_ROWS)
        first = events[0]
        invalid_first = ResolvedEvent(
            "scope:other", first.episode_ref, first.event_ref, first.sequence,
            first.event_kind, first.actor_class, first.code, first.related_ref
        )

        class InvalidResolver:
            def resolve(self, scope_ref: str, episode_ref: str, max_event_refs: int) -> Resolution:
                return Resolution("resolved", "none", (invalid_first, *events[1:]), COMPLETE_ADMISSION)

        with self.assertRaisesRegex(ValueError, "^source_resolution_contract_invalid$"):
            assemble_episode(
                InvalidResolver(), "scope:approved", FIXTURE_EPISODE_REF, "human-calibration-v1", max_event_refs=7
            )

    def test_assembler_sanitizes_source_adapter_exceptions(self) -> None:
        class ExplodingResolver:
            def resolve(self, scope_ref: str, episode_ref: str, max_event_refs: int) -> Resolution:
                raise RuntimeError("raw_source_content_marker")

        with self.assertRaisesRegex(ValueError, "^source_read_failed$") as caught:
            assemble_episode(
                ExplodingResolver(), "scope:approved", FIXTURE_EPISODE_REF, "human-calibration-v1", max_event_refs=7
            )
        self.assertNotIn("raw_source_content_marker", str(caught.exception))

    def test_resolver_forces_read_only_and_control_database_is_writable(self) -> None:
        with tempfile.TemporaryDirectory() as protected_tmp:
            protected_path = _make_store(Path(protected_tmp))
            before = _sha256(protected_path)
            protected = sqlite3.connect(str(protected_path))
            try:
                ReadOnlyFixtureResolver(protected, {"scope:approved"}, max_event_refs=7)
                self.assertEqual(protected.execute("PRAGMA query_only").fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    protected.execute(
                        "INSERT INTO wp5_events "
                        "(scope_ref, episode_ref, event_ref, sequence, event_kind, actor_class, code, related_ref) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        ("scope:approved", FIXTURE_EPISODE_REF, "evidence:write-attempt", 7, "evidence", "source", "supports", None),
                    )
                with self.assertRaises(sqlite3.OperationalError):
                    protected.execute("CREATE TABLE forbidden (value TEXT)")
                protected.rollback()
                self.assertEqual(_sha256(protected_path), before)
            finally:
                protected.close()

        with tempfile.TemporaryDirectory() as control_tmp:
            control_path = _make_store(Path(control_tmp))
            before = _sha256(control_path)
            control = sqlite3.connect(str(control_path))
            try:
                control.execute(
                    "INSERT INTO wp5_events "
                    "(scope_ref, episode_ref, event_ref, sequence, event_kind, actor_class, code, related_ref) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("scope:approved", FIXTURE_EPISODE_REF, "evidence:write-control", 7, "evidence", "source", "supports", None),
                )
                control.commit()
                self.assertNotEqual(_sha256(control_path), before)
            finally:
                control.close()

    def test_unapproved_scope_fails_and_approved_control_resolves_same_episode(self) -> None:
        result = self.resolver.resolve("scope:other", FIXTURE_EPISODE_REF, 7)
        self.assertEqual((result.status, result.reason_code), ("out_of_scope", "scope_not_approved"))
        self.assertEqual(result.events, ())

        other_rows = [tuple(["scope:other", *row[1:]]) for row in BASE_ROWS]
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), other_rows)
            connection = _open_readonly(path)
            try:
                restricted = ReadOnlyFixtureResolver(
                    connection, {"scope:approved", "scope:other"}, max_event_refs=7
                )
                denied = restricted.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
                self.assertEqual((denied.status, denied.reason_code), ("out_of_scope", "episode_scope_mismatch"))
                allowed = ReadOnlyFixtureResolver(connection, {"scope:other"}, max_event_refs=7)
                control = allowed.resolve("scope:other", FIXTURE_EPISODE_REF, 7)
                self.assertEqual(control.status, "resolved")
                self.assertEqual(len(control.events), 7)
            finally:
                connection.close()

    def test_cross_scope_event_row_fails_closed(self) -> None:
        rows = list(BASE_ROWS)
        rows[1] = ("scope:other", *rows[1][1:])
        manifests = [_manifest(expected_event_count=7)]
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), rows, manifests=manifests)
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=7)
                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
                self.assertEqual((result.status, result.reason_code), ("out_of_scope", "event_scope_mismatch"))
                self.assertEqual(result.events, ())
            finally:
                connection.close()

    def test_missing_manifest_is_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), manifests=[])
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=7)
                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
                self.assertEqual((result.status, result.reason_code), ("not_found", "episode_manifest_not_found"))
            finally:
                connection.close()

    def test_duplicate_manifest_is_rejected(self) -> None:
        manifest = _manifest()
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), manifests=[manifest, manifest])
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=7)
                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
                self.assertEqual((result.status, result.reason_code), ("input_unavailable", "duplicate_episode_manifest"))
                self.assertEqual(result.events, ())
            finally:
                connection.close()

    def test_open_manifest_is_rejected_before_event_rows_are_read(self) -> None:
        manifest = _manifest(status="open")
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), manifests=[manifest])
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=7)
                statements: list[str] = []
                connection.set_trace_callback(statements.append)
                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
                self.assertEqual((result.status, result.reason_code), ("input_unavailable", "episode_not_closed"))
                self.assertFalse(any("FROM wp5_events" in statement for statement in statements))
            finally:
                connection.close()

    def test_unknown_manifest_versions_are_rejected(self) -> None:
        manifest = _manifest(codebook_version="unknown-codebook")
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), manifests=[manifest])
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=7)
                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
                self.assertEqual((result.status, result.reason_code), ("input_unavailable", "manifest_contract_violation"))
            finally:
                connection.close()

    def test_manifest_count_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), manifests=[_manifest(expected_event_count=8)])
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=8)
                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 8)
                self.assertEqual(
                    (result.status, result.reason_code),
                    ("input_unavailable", "manifest_event_count_mismatch"),
                )
            finally:
                connection.close()

    def test_manifest_count_over_caller_budget_is_rejected_before_event_read(self) -> None:
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), manifests=[_manifest(expected_event_count=8)])
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=8)
                statements: list[str] = []
                connection.set_trace_callback(statements.append)
                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
                self.assertEqual((result.status, result.reason_code), ("input_unavailable", "event_ref_budget_exceeded"))
                self.assertFalse(any("FROM wp5_events" in statement for statement in statements))
            finally:
                connection.close()

    def test_explicit_positive_reference_budget_has_below_at_and_above_controls(self) -> None:
        parameter = inspect.signature(self.resolver.resolve).parameters["max_event_refs"]
        self.assertIs(parameter.default, inspect.Parameter.empty)

        below = ReadOnlyFixtureResolver(self.connection, {"scope:approved"}, max_event_refs=7)
        rejected = below.resolve("scope:approved", FIXTURE_EPISODE_REF, 6)
        self.assertEqual((rejected.status, rejected.reason_code), ("input_unavailable", "event_ref_budget_exceeded"))
        self.assertEqual(rejected.events, ())
        too_high = below.resolve("scope:approved", FIXTURE_EPISODE_REF, 8)
        self.assertEqual((too_high.status, too_high.reason_code), ("input_unavailable", "event_ref_budget_exceeds_resolver_limit"))

        at_limit = self.resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
        self.assertEqual(at_limit.status, "resolved")
        self.assertEqual(len(at_limit.events), 7)

        above = ReadOnlyFixtureResolver(self.connection, {"scope:approved"}, max_event_refs=8)
        self.assertEqual(above.resolve("scope:approved", FIXTURE_EPISODE_REF, 8).status, "resolved")

        for invalid_budget in (0, -1, True, 1.5):
            with self.subTest(invalid_call_budget=invalid_budget):
                result = self.resolver.resolve(
                    "scope:approved", FIXTURE_EPISODE_REF, cast(int, invalid_budget)
                )
                self.assertEqual(
                    (result.status, result.reason_code),
                    ("input_unavailable", "invalid_event_ref_budget"),
                )

        invalid_budgets: Tuple[object, ...] = (0, -1, True, 1.5)
        for invalid_budget in invalid_budgets:
            with self.subTest(invalid_constructor_budget=invalid_budget):
                with self.assertRaisesRegex(ValueError, "^invalid_event_ref_budget$"):
                    ReadOnlyFixtureResolver(
                        self.connection,
                        {"scope:approved"},
                        max_event_refs=cast(int, invalid_budget),
                    )

    def test_duplicate_source_event_ref_is_rejected_with_valid_unique_control(self) -> None:
        duplicate = ("scope:approved", FIXTURE_EPISODE_REF, "question:q0", 7, "question_initial", "user", "initial_question", None)
        with tempfile.TemporaryDirectory() as duplicate_tmp:
            path = _make_store(Path(duplicate_tmp), BASE_ROWS + [duplicate], unique_event_ref=False)
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=8)
                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 8)
                self.assertEqual((result.status, result.reason_code), ("input_unavailable", "duplicate_source_event_ref"))
                self.assertEqual(result.events, ())
            finally:
                connection.close()

        self.assertEqual(self.resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7).status, "resolved")

    def test_sequence_gap_is_rejected_before_assembly(self) -> None:
        rows = list(BASE_ROWS)
        rows[-1] = tuple([*rows[-1][:3], 7, *rows[-1][4:]])
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), rows)
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=7)
                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
                self.assertEqual((result.status, result.reason_code), ("input_unavailable", "event_sequence_invalid"))
            finally:
                connection.close()

    def test_duplicate_sequence_is_rejected_before_assembly(self) -> None:
        duplicate_sequence = (
            "scope:approved", FIXTURE_EPISODE_REF, "evidence:e1", 6, "evidence", "source", "supports", None
        )
        rows = BASE_ROWS + [duplicate_sequence]
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), rows)
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=8)
                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 8)
                self.assertEqual((result.status, result.reason_code), ("input_unavailable", "event_sequence_invalid"))
            finally:
                connection.close()

    def test_causality_that_cannot_be_proven_is_partial(self) -> None:
        rows = [
            BASE_ROWS[0],
            ("scope:approved", FIXTURE_EPISODE_REF, "feedback:f0", 1, "feedback", "user", "acceptance", "question:q1"),
            ("scope:approved", FIXTURE_EPISODE_REF, "question:q1", 2, "question_update", "agent", "evidence_driven", "evidence:e0"),
            ("scope:approved", FIXTURE_EPISODE_REF, "evidence:e0", 3, "evidence", "source", "supports", None),
            BASE_ROWS[4],
            BASE_ROWS[5],
            BASE_ROWS[6],
        ]
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), rows)
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=7)
                episode = assemble_episode(resolver, "scope:approved", FIXTURE_EPISODE_REF, "human-calibration-v1", max_event_refs=7)
                self.assertEqual(episode.trajectory_status, "partial")
                self.assertIn("update_cause_unproven", episode.reason_codes)
            finally:
                connection.close()

    def test_user_correction_before_agent_update_is_classified_separately(self) -> None:
        rows = [
            BASE_ROWS[0],
            ("scope:approved", FIXTURE_EPISODE_REF, "feedback:f1", 1, "feedback", "user", "correction", None),
            ("scope:approved", FIXTURE_EPISODE_REF, "question:q1", 2, "question_update", "agent", "user_correction", "feedback:f1"),
            ("scope:approved", FIXTURE_EPISODE_REF, "evidence:e0", 3, "evidence", "source", "supports", None),
            BASE_ROWS[4],
            BASE_ROWS[5],
            BASE_ROWS[6],
        ]
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), rows)
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=7)
                episode = assemble_episode(resolver, "scope:approved", FIXTURE_EPISODE_REF, "human-calibration-v1", max_event_refs=7)
                self.assertEqual(episode.causal_order, "user_judgment_agent_structuring")
                self.assertEqual(episode.trajectory_status, "complete")
            finally:
                connection.close()

    def test_missing_initial_question_is_not_observable_when_manifest_is_complete(self) -> None:
        source_rows = [row for row in BASE_ROWS if row[4] != "question_initial"]
        rows = [tuple([*row[:3], index, *row[4:]]) for index, row in enumerate(source_rows)]
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), rows)
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=7)
                episode = assemble_episode(resolver, "scope:approved", FIXTURE_EPISODE_REF, "human-calibration-v1", max_event_refs=7)
                self.assertEqual(episode.trajectory_status, "not_observable")
                self.assertIn("initial_question_missing", episode.reason_codes)
                with self.assertRaisesRegex(ValueError, "^episode_not_observable$"):
                    build_blind_calibration_packet(episode, "case:case-4", 4096)
            finally:
                connection.close()

    def test_unknown_code_and_raw_identifier_rows_are_rejected_without_echo(self) -> None:
        sentinel = "RAW_TRANSCRIPT_SENTINEL_DO_NOT_LEAK"
        rows = list(BASE_ROWS)
        rows[1] = tuple([*rows[1][:6], sentinel, rows[1][7]])
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), rows)
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=7)
                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
                self.assertEqual((result.status, result.reason_code), ("input_unavailable", "source_contract_violation"))
                self.assertNotIn(sentinel, repr(result))
            finally:
                connection.close()

        rows = list(BASE_ROWS)
        rows[1] = tuple([rows[1][0], rows[1][1], "session:raw-id", *rows[1][3:]])
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), rows)
            connection = _open_readonly(path)
            try:
                resolver = ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=7)
                result = resolver.resolve("scope:approved", FIXTURE_EPISODE_REF, 7)
                self.assertEqual((result.status, result.reason_code), ("input_unavailable", "source_contract_violation"))
            finally:
                connection.close()

    def test_unexpected_source_columns_and_objects_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp), extra_column=True)
            before = _sha256(path)
            connection = _open_readonly(path)
            try:
                with self.assertRaisesRegex(ValueError, "^source_schema_invalid$"):
                    ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=7)
                self.assertEqual(_sha256(path), before)
            finally:
                connection.close()

        with tempfile.TemporaryDirectory() as other_tmp:
            path = _make_store(Path(other_tmp))
            connection = sqlite3.connect(str(path))
            connection.execute("CREATE VIEW unexpected AS SELECT event_ref FROM wp5_events")
            connection.commit()
            connection.close()
            connection = _open_readonly(path)
            try:
                with self.assertRaisesRegex(ValueError, "^source_schema_invalid$"):
                    ReadOnlyFixtureResolver(connection, {"scope:approved"}, max_event_refs=7)
            finally:
                connection.close()

    def test_blind_packet_requires_positive_caller_budget(self) -> None:
        episode = assemble_episode(self.resolver, "scope:approved", FIXTURE_EPISODE_REF, "human-calibration-v1", max_event_refs=7)
        with self.assertRaisesRegex(ValueError, "^invalid_packet_budget$"):
            build_blind_calibration_packet(episode, "case:case-5", 0)
        with self.assertRaisesRegex(ValueError, "^packet_exceeds_budget$"):
            build_blind_calibration_packet(episode, "case:case-5", 1)

    def test_packet_builder_rejects_forged_free_text_fields(self) -> None:
        episode = assemble_episode(self.resolver, "scope:approved", FIXTURE_EPISODE_REF, "human-calibration-v1", max_event_refs=7)
        sentinel = "RAW_TRANSCRIPT_SENTINEL_DO_NOT_LEAK"
        forged = replace(episode, update_reason_codes=(sentinel,))
        with self.assertRaisesRegex(ValueError, "^episode_contract_invalid$") as raised:
            build_blind_calibration_packet(forged, "case:case-6", 4096)
        self.assertNotIn(sentinel, str(raised.exception))

    def test_packet_builder_rejects_inconsistent_episode_claims(self) -> None:
        episode = assemble_episode(self.resolver, "scope:approved", FIXTURE_EPISODE_REF, "human-calibration-v1", max_event_refs=7)
        forged_variants = (
            replace(episode, event_refs=()),
            replace(episode, trajectory_status="complete", reason_codes=("required_trace_component_missing",)),
            replace(episode, event_refs=([],)),
        )
        for forged in forged_variants:
            with self.subTest(forged=forged):
                with self.assertRaisesRegex(ValueError, "^episode_contract_invalid$"):
                    build_blind_calibration_packet(forged, "case:case-7", 4096)

    def test_invalid_episode_reference_is_rejected(self) -> None:
        result = self.resolver.resolve("scope:approved", "session:discord-raw-id", 7)
        self.assertEqual((result.status, result.reason_code), ("input_unavailable", "invalid_episode_ref"))


if __name__ == "__main__":
    unittest.main()
