#!/usr/bin/env python3
"""Fixture-only WP5 episode assembly and blind calibration packet prototype.

This module accepts an application-owned, read-only SQLite connection. It has no
CLI, opens no database itself, writes no files, and emits no conversation text.
Only closed event codes and caller-supplied opaque references cross its boundary.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional, Protocol, Sequence, Tuple


_SOURCE_MANIFEST_TABLE = "wp5_episodes"
_SOURCE_EVENT_TABLE = "wp5_events"
_SOURCE_TABLES = (_SOURCE_MANIFEST_TABLE, _SOURCE_EVENT_TABLE)
_FIXTURE_PRODUCER_VERSION = "wp4-wp5-fixture-v0"
_FIXTURE_CODEBOOK_VERSION = "wp5-fixture-codebook-v0"
_MANIFEST_COLUMNS = (
    "scope_ref",
    "episode_ref",
    "producer_version",
    "codebook_version",
    "status",
    "expected_event_count",
)
_EVENT_COLUMNS = (
    "scope_ref",
    "episode_ref",
    "event_ref",
    "sequence",
    "event_kind",
    "actor_class",
    "code",
    "related_ref",
)
_REF_RE = re.compile(r"^(scope|episode|event|question|evidence|feedback|decision|validation|scope_topic|case):[A-Za-z0-9][A-Za-z0-9._-]*$")
_KIND_PREFIX = {
    "question_initial": "question",
    "question_update": "question",
    "evidence": "evidence",
    "feedback": "feedback",
    "decision": "decision",
    "next_validation": "validation",
    "deferred_scope": "scope_topic",
}
_ALLOWED_CODES = {
    "question_initial": frozenset({"initial_question"}),
    "question_update": frozenset({"evidence_driven", "user_correction", "user_direction", "rollback", "reframed"}),
    "evidence": frozenset({"supports", "contradicts", "insufficient"}),
    "feedback": frozenset({"correction", "acceptance", "positive_signal", "rejection"}),
    "decision": frozenset({"go", "conditional_go", "no_go", "on_hold", "provisionally_locked"}),
    "next_validation": frozenset({"customer_interview", "payer_validation", "technical_validation", "evidence_review", "human_review"}),
    "deferred_scope": frozenset({"customer", "payer", "budget", "pilot", "implementation", "external_review", "other"}),
}
_ALLOWED_ACTORS = {
    "question_initial": frozenset({"user"}),
    "question_update": frozenset({"agent"}),
    "evidence": frozenset({"source", "agent"}),
    "feedback": frozenset({"user"}),
    "decision": frozenset({"user", "agent"}),
    "next_validation": frozenset({"user", "agent"}),
    "deferred_scope": frozenset({"user", "agent"}),
}
_CALIBRATION_AXES = (
    "initial_question_capture",
    "evidence_driven_update",
    "question_update_rationale",
    "decision_proximity",
    "feedback_interpretation",
)


@dataclass(frozen=True)
class ResolvedEvent:
    scope_ref: str
    episode_ref: str
    event_ref: str
    sequence: int
    event_kind: str
    actor_class: str
    code: str
    related_ref: Optional[str]


@dataclass(frozen=True)
class AdmissionEvidence:
    """Adapter-reported completeness checks; not proof of source authenticity."""

    capture_complete: bool
    episode_boundary_verified: bool
    single_lineage_verified: bool
    source_order_verified: bool
    inactive_history_resolved: bool
    compacted_history_resolved: bool
    pagination_complete: bool
    recovery_reconciled: bool


@dataclass(frozen=True)
class Resolution:
    status: str
    reason_code: str
    events: Tuple[ResolvedEvent, ...] = ()
    admission: Optional[AdmissionEvidence] = None


class EpisodeResolver(Protocol):
    """Return complete coded rows and admission evidence without body content."""

    def resolve(self, scope_ref: str, episode_ref: str, max_event_refs: int) -> Resolution: ...


_ALLOWED_RESOLUTION_STATUSES = frozenset({"resolved", "input_unavailable", "out_of_scope", "not_found"})
_REASON_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")
_ALLOWED_RESOLUTION_REASONS = frozenset({
    "none",
    "invalid_event_ref_budget",
    "event_ref_budget_exceeds_resolver_limit",
    "invalid_scope_ref",
    "scope_not_approved",
    "invalid_episode_ref",
    "episode_manifest_not_found",
    "duplicate_episode_manifest",
    "episode_scope_mismatch",
    "manifest_contract_violation",
    "episode_not_closed",
    "event_ref_budget_exceeded",
    "manifest_event_count_mismatch",
    "event_scope_mismatch",
    "source_contract_violation",
    "source_read_failed",
    "duplicate_source_event_ref",
    "event_sequence_invalid",
    "capture_incomplete",
    "inactive_history_unresolved",
    "compacted_history_unresolved",
    "lineage_unresolved",
    "pagination_incomplete",
    "recovery_unreconciled",
})


@contextmanager
def _read_snapshot(connection: sqlite3.Connection) -> Iterator[None]:
    """Keep all resolver SELECTs on one SQLite snapshot, including nested callers."""
    connection.execute("SAVEPOINT wp5_episode_resolver_snapshot")
    try:
        yield
    finally:
        connection.execute("RELEASE wp5_episode_resolver_snapshot")


@dataclass(frozen=True)
class Episode:
    episode_ref: str
    scope_ref: str
    rubric_version: str
    event_refs: Tuple[str, ...]
    trajectory_status: str
    causal_order: str
    reason_codes: Tuple[str, ...]
    initial_question_refs: Tuple[str, ...]
    question_update_refs: Tuple[str, ...]
    update_reason_codes: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    feedback_types: Tuple[str, ...]
    decision_statuses: Tuple[str, ...]
    next_validation_codes: Tuple[str, ...]
    deferred_scope_codes: Tuple[str, ...]


@dataclass(frozen=True)
class BlindCalibrationPacket:
    """Transient, metadata-only handoff; prior rater data has no field here."""

    case_ref: str
    rubric_version: str
    axes: Tuple[str, ...]
    trajectory_status: str
    causal_order: str
    initial_question_refs: Tuple[str, ...]
    question_update_refs: Tuple[str, ...]
    update_reason_codes: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    feedback_types: Tuple[str, ...]
    decision_statuses: Tuple[str, ...]
    next_validation_codes: Tuple[str, ...]
    deferred_scope_codes: Tuple[str, ...]


class ReadOnlyFixtureResolver:
    """Resolve one complete, closed episode from an injected SQLite fixture."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        approved_scope_refs: Iterable[str],
        max_event_refs: int,
    ):
        self._connection = connection
        self._approved_scopes = frozenset(approved_scope_refs)
        if isinstance(max_event_refs, bool) or not isinstance(max_event_refs, int) or max_event_refs <= 0:
            raise ValueError("invalid_event_ref_budget")
        self._max_event_refs = max_event_refs
        if not self._approved_scopes or any(not _valid_ref(item, "scope") for item in self._approved_scopes):
            raise ValueError("invalid_approved_scope_set")
        try:
            self._connection.execute("PRAGMA query_only = ON")
            query_only = self._connection.execute("PRAGMA query_only").fetchone()
            if query_only is None or query_only[0] != 1:
                raise ValueError("source_read_only_unavailable")
            self._validate_source_schema()
        except (sqlite3.Error, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc) in {
                "invalid_approved_scope_set",
                "source_read_only_unavailable",
                "source_schema_invalid",
            }:
                raise
            raise ValueError("source_schema_invalid") from None

    def _validate_source_schema(self) -> None:
        objects = self._connection.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table', 'view', 'trigger') AND name NOT GLOB 'sqlite_*' "
            "ORDER BY type, name"
        ).fetchall()
        expected = [(name, "table") for name in _SOURCE_TABLES]
        if objects != expected:
            raise ValueError("source_schema_invalid")
        manifest_columns = self._connection.execute("PRAGMA table_info(wp5_episodes)").fetchall()
        event_columns = self._connection.execute("PRAGMA table_info(wp5_events)").fetchall()
        if tuple(row[1] for row in manifest_columns) != _MANIFEST_COLUMNS:
            raise ValueError("source_schema_invalid")
        if tuple(row[1] for row in event_columns) != _EVENT_COLUMNS:
            raise ValueError("source_schema_invalid")

    def resolve(self, scope_ref: str, episode_ref: str, max_event_refs: int) -> Resolution:
        if isinstance(max_event_refs, bool) or not isinstance(max_event_refs, int) or max_event_refs <= 0:
            return Resolution("input_unavailable", "invalid_event_ref_budget")
        if max_event_refs > self._max_event_refs:
            return Resolution("input_unavailable", "event_ref_budget_exceeds_resolver_limit")
        if not _valid_ref(scope_ref, "scope"):
            return Resolution("input_unavailable", "invalid_scope_ref")
        if scope_ref not in self._approved_scopes:
            return Resolution("out_of_scope", "scope_not_approved")
        if not _valid_ref(episode_ref, "episode"):
            return Resolution("input_unavailable", "invalid_episode_ref")

        try:
            with _read_snapshot(self._connection):
                manifests = self._connection.execute(
                    "SELECT scope_ref, episode_ref, producer_version, codebook_version, status, expected_event_count "
                    "FROM wp5_episodes WHERE episode_ref = ? LIMIT 2",
                    (episode_ref,),
                ).fetchmany(2)
                if not manifests:
                    return Resolution("not_found", "episode_manifest_not_found")
                if len(manifests) != 1:
                    return Resolution("input_unavailable", "duplicate_episode_manifest")
                scope, manifest_episode, producer_version, codebook_version, status, event_count = manifests[0]
                if scope != scope_ref:
                    return Resolution("out_of_scope", "episode_scope_mismatch")
                if (
                    manifest_episode != episode_ref
                    or producer_version != _FIXTURE_PRODUCER_VERSION
                    or codebook_version != _FIXTURE_CODEBOOK_VERSION
                    or status not in {"open", "closed"}
                    or isinstance(event_count, bool)
                    or not isinstance(event_count, int)
                    or event_count <= 0
                ):
                    return Resolution("input_unavailable", "manifest_contract_violation")
                if status != "closed":
                    return Resolution("input_unavailable", "episode_not_closed")
                if event_count > max_event_refs:
                    return Resolution("input_unavailable", "event_ref_budget_exceeded")

                rows = self._connection.execute(
                    "SELECT scope_ref, episode_ref, event_ref, sequence, event_kind, actor_class, code, related_ref "
                    "FROM wp5_events WHERE episode_ref = ? ORDER BY sequence LIMIT ?",
                    (episode_ref, max_event_refs + 1),
                ).fetchmany(max_event_refs + 1)
                if len(rows) > max_event_refs:
                    return Resolution("input_unavailable", "event_ref_budget_exceeded")
                if len(rows) != event_count:
                    return Resolution("input_unavailable", "manifest_event_count_mismatch")

                events = []
                for row in rows:
                    if row[0] != scope_ref or row[1] != episode_ref:
                        return Resolution("out_of_scope", "event_scope_mismatch")
                    event = _validated_event(row)
                    if event is None:
                        return Resolution("input_unavailable", "source_contract_violation")
                    events.append(event)
        except sqlite3.Error:
            return Resolution("input_unavailable", "source_read_failed")

        if len({event.event_ref for event in events}) != len(events):
            return Resolution("input_unavailable", "duplicate_source_event_ref")
        if [event.sequence for event in events] != list(range(event_count)):
            return Resolution("input_unavailable", "event_sequence_invalid")
        return Resolution(
            "resolved",
            "none",
            tuple(events),
            AdmissionEvidence(
                capture_complete=True,
                episode_boundary_verified=True,
                single_lineage_verified=True,
                source_order_verified=True,
                inactive_history_resolved=True,
                compacted_history_resolved=True,
                pagination_complete=True,
                recovery_reconciled=True,
            ),
        )


def _validated_resolution_events(
    resolution: object, scope_ref: str, episode_ref: str, max_event_refs: int
) -> Tuple[ResolvedEvent, ...]:
    if not isinstance(resolution, Resolution):
        raise ValueError("source_resolution_contract_invalid")
    if (
        not isinstance(resolution.status, str)
        or resolution.status not in _ALLOWED_RESOLUTION_STATUSES
        or not isinstance(resolution.reason_code, str)
        or _REASON_CODE_PATTERN.fullmatch(resolution.reason_code) is None
        or resolution.reason_code not in _ALLOWED_RESOLUTION_REASONS
        or not isinstance(resolution.events, tuple)
    ):
        raise ValueError("source_resolution_contract_invalid")
    if resolution.status != "resolved":
        if resolution.reason_code == "none" or resolution.events or resolution.admission is not None:
            raise ValueError("source_resolution_contract_invalid")
        raise ValueError("source_" + resolution.reason_code)
    if resolution.reason_code != "none" or not resolution.events:
        raise ValueError("source_resolution_contract_invalid")
    if len(resolution.events) > max_event_refs:
        raise ValueError("source_event_ref_budget_exceeded")
    if resolution.admission is None:
        raise ValueError("source_admission_evidence_missing")
    if not isinstance(resolution.admission, AdmissionEvidence):
        raise ValueError("source_resolution_contract_invalid")
    admission_values = (
        resolution.admission.capture_complete,
        resolution.admission.episode_boundary_verified,
        resolution.admission.single_lineage_verified,
        resolution.admission.source_order_verified,
        resolution.admission.inactive_history_resolved,
        resolution.admission.compacted_history_resolved,
        resolution.admission.pagination_complete,
        resolution.admission.recovery_reconciled,
    )
    if any(type(value) is not bool for value in admission_values):
        raise ValueError("source_resolution_contract_invalid")
    if any(value is not True for value in admission_values):
        raise ValueError("source_admission_incomplete")

    events: List[ResolvedEvent] = []
    for event in resolution.events:
        if not isinstance(event, ResolvedEvent):
            raise ValueError("source_resolution_contract_invalid")
        normalized = _validated_event((
            event.scope_ref,
            event.episode_ref,
            event.event_ref,
            event.sequence,
            event.event_kind,
            event.actor_class,
            event.code,
            event.related_ref,
        ))
        if (
            normalized is None
            or normalized != event
            or event.scope_ref != scope_ref
            or event.episode_ref != episode_ref
        ):
            raise ValueError("source_resolution_contract_invalid")
        events.append(normalized)
    if (
        [event.sequence for event in events] != list(range(len(events)))
        or len({event.event_ref for event in events}) != len(events)
    ):
        raise ValueError("source_resolution_contract_invalid")
    return tuple(events)


def assemble_episode(
    resolver: EpisodeResolver,
    scope_ref: str,
    episode_ref: str,
    rubric_version: str,
    max_event_refs: int,
) -> Episode:
    """Assemble a source-resolved, closed episode from verified coded rows."""
    if not _valid_ref(episode_ref, "episode"):
        raise ValueError("invalid_episode_ref")
    if not _valid_version(rubric_version):
        raise ValueError("invalid_rubric_version")
    if isinstance(max_event_refs, bool) or not isinstance(max_event_refs, int) or max_event_refs <= 0:
        raise ValueError("invalid_event_ref_budget")
    try:
        resolution = resolver.resolve(scope_ref, episode_ref, max_event_refs)
    except Exception:
        raise ValueError("source_read_failed") from None
    events = _validated_resolution_events(resolution, scope_ref, episode_ref, max_event_refs)
    return _assemble_resolved(events, episode_ref, scope_ref, rubric_version)


def _assemble_resolved(
    events: Tuple[ResolvedEvent, ...], episode_ref: str, scope_ref: str, rubric_version: str
) -> Episode:
    reason_codes: List[str] = []
    sequences = [item.sequence for item in events]
    if len(set(sequences)) != len(sequences):
        reason_codes.append("ambiguous_sequence")

    by_ref = {item.event_ref: item for item in events}
    initial = [item for item in events if item.event_kind == "question_initial"]
    updates = [item for item in events if item.event_kind == "question_update"]
    evidence = [item for item in events if item.event_kind == "evidence"]
    feedback = [item for item in events if item.event_kind == "feedback"]
    decisions = [item for item in events if item.event_kind == "decision"]
    next_validation = [item for item in events if item.event_kind == "next_validation"]
    deferred = [item for item in events if item.event_kind == "deferred_scope"]

    if not initial:
        trajectory_status = "not_observable"
        reason_codes.append("initial_question_missing")
    else:
        required = (updates, evidence, feedback, decisions, next_validation, deferred)
        if any(not items for items in required):
            reason_codes.append("required_trace_component_missing")
        if len(initial) != 1:
            reason_codes.append("initial_question_ambiguous")
        if any(len(set(item.sequence for item in group)) != len(group) for group in (initial, updates, evidence, feedback, decisions, next_validation, deferred)):
            if "ambiguous_sequence" not in reason_codes:
                reason_codes.append("ambiguous_sequence")

        for update in updates:
            related = by_ref.get(update.related_ref or "")
            if related is None or related.sequence >= update.sequence:
                reason_codes.append("update_cause_unproven")
                continue
            if related.event_kind == "evidence":
                if update.code != "evidence_driven":
                    reason_codes.append("update_cause_unproven")
                if not any(item.related_ref == update.event_ref and item.sequence > update.sequence for item in feedback):
                    reason_codes.append("post_update_user_judgment_missing")
            elif related.event_kind == "feedback":
                if update.code not in {"user_correction", "user_direction", "rollback", "reframed"}:
                    reason_codes.append("update_cause_unproven")
                if related.code not in {"correction", "rejection", "acceptance", "positive_signal"}:
                    reason_codes.append("update_cause_unproven")
            else:
                reason_codes.append("update_cause_unproven")

        reasons = set(reason_codes)
        trajectory_status = "complete" if not reasons else "partial"

    causal_order = _causal_order(updates, by_ref, feedback)
    if updates and causal_order == "not_observable" and "causal_order_unobservable" not in reason_codes:
        reason_codes.append("causal_order_unobservable")
        if trajectory_status == "complete":
            trajectory_status = "partial"

    return Episode(
        episode_ref=episode_ref,
        scope_ref=scope_ref,
        rubric_version=rubric_version,
        event_refs=tuple(item.event_ref for item in events),
        trajectory_status=trajectory_status,
        causal_order=causal_order,
        reason_codes=tuple(sorted(set(reason_codes))),
        initial_question_refs=tuple(item.event_ref for item in initial),
        question_update_refs=tuple(item.event_ref for item in updates),
        update_reason_codes=tuple(item.code for item in updates),
        evidence_refs=tuple(item.event_ref for item in evidence),
        feedback_types=tuple(item.code for item in feedback),
        decision_statuses=tuple(item.code for item in decisions),
        next_validation_codes=tuple(item.code for item in next_validation),
        deferred_scope_codes=tuple(item.code for item in deferred),
    )


def build_blind_calibration_packet(
    episode: Episode, case_ref: str, max_packet_bytes: int
) -> BlindCalibrationPacket:
    """Build a metadata-only in-memory packet; do not print or persist it."""
    if not _valid_episode(episode):
        raise ValueError("episode_contract_invalid")
    if not _valid_ref(case_ref, "case"):
        raise ValueError("invalid_case_ref")
    if isinstance(max_packet_bytes, bool) or not isinstance(max_packet_bytes, int) or max_packet_bytes <= 0:
        raise ValueError("invalid_packet_budget")
    if episode.trajectory_status == "not_observable":
        raise ValueError("episode_not_observable")
    packet = BlindCalibrationPacket(
        case_ref=case_ref,
        rubric_version=episode.rubric_version,
        axes=_CALIBRATION_AXES,
        trajectory_status=episode.trajectory_status,
        causal_order=episode.causal_order,
        initial_question_refs=episode.initial_question_refs,
        question_update_refs=episode.question_update_refs,
        update_reason_codes=episode.update_reason_codes,
        evidence_refs=episode.evidence_refs,
        feedback_types=episode.feedback_types,
        decision_statuses=episode.decision_statuses,
        next_validation_codes=episode.next_validation_codes,
        deferred_scope_codes=episode.deferred_scope_codes,
    )
    if len(_packet_bytes(packet)) > max_packet_bytes:
        raise ValueError("packet_exceeds_budget")
    return packet


def _valid_episode(episode: object) -> bool:
    if not isinstance(episode, Episode):
        return False
    if not _valid_ref(episode.episode_ref, "episode") or not _valid_ref(episode.scope_ref, "scope"):
        return False
    if not _valid_version(episode.rubric_version):
        return False
    if not isinstance(episode.trajectory_status, str) or episode.trajectory_status not in {"complete", "partial", "not_observable"}:
        return False
    if not isinstance(episode.causal_order, str) or episode.causal_order not in {
        "evidence_agent_update_user_judgment",
        "user_judgment_agent_structuring",
        "not_observable",
    }:
        return False
    ref_groups = (
        (episode.event_refs, None),
        (episode.initial_question_refs, "question"),
        (episode.question_update_refs, "question"),
        (episode.evidence_refs, "evidence"),
    )
    for values, prefix in ref_groups:
        if not isinstance(values, tuple) or not all(_valid_ref(item, prefix) for item in values):
            return False
        if len(set(values)) != len(values):
            return False
    event_ref_set = set(episode.event_refs)
    categorized_refs = (
        episode.initial_question_refs
        + episode.question_update_refs
        + episode.evidence_refs
    )
    if not set(categorized_refs).issubset(event_ref_set):
        return False
    if set(episode.initial_question_refs).intersection(episode.question_update_refs):
        return False
    code_groups = (
        (episode.update_reason_codes, _ALLOWED_CODES["question_update"]),
        (episode.feedback_types, _ALLOWED_CODES["feedback"]),
        (episode.decision_statuses, _ALLOWED_CODES["decision"]),
        (episode.next_validation_codes, _ALLOWED_CODES["next_validation"]),
        (episode.deferred_scope_codes, _ALLOWED_CODES["deferred_scope"]),
    )
    for values, allowed in code_groups:
        if not isinstance(values, tuple) or any(not isinstance(item, str) or item not in allowed for item in values):
            return False
    allowed_reasons = {
        "ambiguous_sequence",
        "initial_question_missing",
        "initial_question_ambiguous",
        "required_trace_component_missing",
        "update_cause_unproven",
        "post_update_user_judgment_missing",
        "causal_order_unobservable",
    }
    if not isinstance(episode.reason_codes, tuple) or any(
        not isinstance(item, str) or item not in allowed_reasons for item in episode.reason_codes
    ):
        return False
    if len(set(episode.reason_codes)) != len(episode.reason_codes):
        return False

    if len(episode.update_reason_codes) != len(episode.question_update_refs):
        return False
    if episode.trajectory_status == "complete":
        if (
            episode.reason_codes
            or len(episode.initial_question_refs) != 1
            or not episode.question_update_refs
            or not episode.evidence_refs
            or not episode.feedback_types
            or not episode.decision_statuses
            or not episode.next_validation_codes
            or not episode.deferred_scope_codes
            or episode.causal_order == "not_observable"
        ):
            return False
    elif episode.trajectory_status == "partial":
        if not episode.initial_question_refs or not episode.reason_codes:
            return False
    elif episode.trajectory_status == "not_observable":
        if episode.initial_question_refs or "initial_question_missing" not in episode.reason_codes:
            return False

    if episode.causal_order != "not_observable" and not episode.question_update_refs:
        return False
    if episode.question_update_refs and episode.causal_order == "not_observable":
        if "causal_order_unobservable" not in episode.reason_codes:
            return False
    elif episode.causal_order == "evidence_agent_update_user_judgment":
        if not episode.evidence_refs or not episode.feedback_types:
            return False
    elif episode.causal_order == "user_judgment_agent_structuring" and not episode.feedback_types:
        return False
    return True


def _packet_bytes(packet: BlindCalibrationPacket) -> bytes:
    data = {
        "case_ref": packet.case_ref,
        "rubric_version": packet.rubric_version,
        "axes": packet.axes,
        "trajectory_status": packet.trajectory_status,
        "causal_order": packet.causal_order,
        "initial_question_refs": packet.initial_question_refs,
        "question_update_refs": packet.question_update_refs,
        "update_reason_codes": packet.update_reason_codes,
        "evidence_refs": packet.evidence_refs,
        "feedback_types": packet.feedback_types,
        "decision_statuses": packet.decision_statuses,
        "next_validation_codes": packet.next_validation_codes,
        "deferred_scope_codes": packet.deferred_scope_codes,
    }
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validated_event(row: Sequence[object]) -> Optional[ResolvedEvent]:
    scope_ref, episode_ref, event_ref, sequence, event_kind, actor_class, code, related_ref = row
    if (
        not _valid_ref(scope_ref, "scope")
        or not _valid_ref(episode_ref, "episode")
        or not _valid_ref(event_ref)
    ):
        return None
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        return None
    if not isinstance(event_kind, str) or not isinstance(actor_class, str) or not isinstance(code, str):
        return None
    if event_kind not in _KIND_PREFIX or actor_class not in _ALLOWED_ACTORS.get(event_kind, frozenset()):
        return None
    if not _valid_ref(event_ref, _KIND_PREFIX[event_kind]):
        return None
    if code not in _ALLOWED_CODES[event_kind]:
        return None
    if event_kind == "question_update":
        if not _valid_ref(related_ref):
            return None
    elif event_kind == "feedback":
        if related_ref is not None and not _valid_ref(related_ref, "question"):
            return None
    elif related_ref is not None:
        return None
    return ResolvedEvent(
        scope_ref=str(scope_ref),
        episode_ref=str(episode_ref),
        event_ref=str(event_ref),
        sequence=sequence,
        event_kind=str(event_kind),
        actor_class=str(actor_class),
        code=str(code),
        related_ref=str(related_ref) if related_ref is not None else None,
    )


def _causal_order(
    updates: Sequence[ResolvedEvent], by_ref: Dict[str, ResolvedEvent], feedback: Sequence[ResolvedEvent]
) -> str:
    if not updates:
        return "not_observable"
    classifications = set()
    for update in updates:
        cause = by_ref.get(update.related_ref or "")
        if cause is None or cause.sequence >= update.sequence:
            return "not_observable"
        if cause.event_kind == "feedback":
            classifications.add("user_judgment_agent_structuring")
        elif cause.event_kind == "evidence" and any(
            item.related_ref == update.event_ref and item.sequence > update.sequence for item in feedback
        ):
            classifications.add("evidence_agent_update_user_judgment")
        else:
            return "not_observable"
    if len(classifications) != 1:
        return "not_observable"
    return next(iter(classifications))


def _valid_ref(value: object, expected_prefix: Optional[str] = None) -> bool:
    if not isinstance(value, str) or _REF_RE.fullmatch(value) is None:
        return False
    if expected_prefix is not None and not value.startswith(expected_prefix + ":"):
        return False
    return True


def _valid_version(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) is not None
