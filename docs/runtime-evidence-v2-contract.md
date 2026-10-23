# Runtime Evidence Envelope V2 — proposal

- Version: 2
- State: **draft for human review; not wired into the production Gateway/Outbox/report/Promotion flow. Isolated Outbox, consumer, and report fixtures are documented in `docs/wp2-durable-transport-design.md`.**
- Schema: `schemas/runtime-evidence-envelope-v2.schema.json`
- Validator: `scripts/runtime_evidence_contract.py`

## Purpose and separation

This envelope records a bounded Gateway transport event. It is not an assessment record. It cannot state a semantic verdict, capability result, or Agent Level. A structurally valid event proves only that a producer supplied metadata matching this contract; it does not prove the source classification, HMAC authenticity, persistence, consumer ACK, ordinary-conversation provenance, or evaluation validity.

The producer fields intentionally use separate axes:

- `transport_status=captured`: the observer created the envelope. It does **not** claim durable outbox storage, consumer persistence, ACK, or report visibility. Outbox/consumer lifecycle states belong to separate transport receipts/reports.
- `measurement_status`: `not_assessed`, `partial`, or `not_observable`. The producer cannot emit `complete`.
- `evaluation_eligibility`: `transport_only` or `excluded`. Semantic eligibility is not assignable by the producer; later eligibility requires a separate consumer and human-calibration decision.
- A `turn_settled` Envelope is created after the Gateway finalizer determines the terminal outcome and persistence-attempt result. It may record `persistence_status=unconfirmed` or `unknown`; that record is `excluded` and does not prove the canonical turn was persisted. Outbox unavailability prevents the Envelope from being retained, so missing rows cannot be interpreted as missing turns; an independent denominator remains a WP2 design prerequisite.

WP2/WP3 must record `outbox_persisted`, `consumer_acknowledged`, `report_visible`, and any later eligibility in distinct transport/report records. They must not rewrite this immutable envelope to make a downstream stage appear complete.

## Allowlisted envelope

The schema requires fixed event type `turn_settled`, Shadow execution, bounded counts, controlled classification enums, and references with an explicit HMAC key-version prefix. All objects reject unknown fields recursively.

The contract excludes:

- user or assistant text, drafts, prompts, tool names/arguments/results, attachments, raw exception strings, paths, raw platform/session/message identifiers;
- hashes of raw conversation content or low-entropy identifiers;
- `level`, `capability_id`, `decision`, `semantic_verdict`, or Promotion result.

The `payload_hash` covers only the canonical serialized allowlisted envelope with `payload_hash` omitted. It is an integrity/deduplication value, not a content digest. Counter ceiling `100000` and envelope ceiling `8192` bytes are defensive draft limits; fixture tests exercise them. They require review against real bounded-runtime behavior before adoption.

Timestamps use a canonical UTC subset: uppercase `T`, uppercase `Z`, no numeric offset, seconds `00`–`59`, and a valid Gregorian calendar date. The Schema pattern rejects impossible month/day combinations and enforces leap-year rules without relying on optional `format` assertion; the local parser also checks the date. This narrows accepted input deliberately to keep stored timestamps and comparisons unambiguous.

## Cross-field rules

1. `persistence_status=confirmed` requires a non-null HMAC-shaped `persistence_receipt_ref`; every other persistence state requires null.
2. `evaluation_eligibility=transport_only` is permitted only for `ordinary_runtime` + `ordinary_task` + `gateway_dispatch`, a non-null `scope_ref`, and a syntactically present persistence receipt with `persistence_status=confirmed`. Other combinations, including unconfirmed persistence, are `excluded`. This is a structural producer claim, not authenticated provenance or semantic eligibility.
3. `started_at` cannot be later than `ended_at` when both exist. All non-null timestamps use the canonical UTC subset described above.
4. Reference shape validation is not HMAC authentication. `persistence_status=confirmed` and a well-shaped receipt reference are also untrusted producer claims until a consumer verifies the receipt against the canonical persistence writer. Neither a structurally valid Envelope nor its classification is an ACK or persistence proof. A future producer/consumer must verify HMACs using an approved profile-scoped key service and must never log or store key material in Evidence, repository, or diagnostics.
5. A configuration fingerprint may cover only an explicitly approved, non-secret manifest. It must not be a hash of prompt text, skill contents, tool descriptions, credentials, or other raw content.

## Privacy threat model

| Threat | Control in this draft | Remaining decision / risk |
|---|---|---|
| Raw conversation or tool data enters persistent evidence | Exact recursive allowlist; schema has no content fields; unknown nested keys rejected. | Future episode resolution must process approved source material read-only and avoid writing it to logs or ledger. |
| Re-identification from stable references | HMAC-shaped references; separate reference types and profile scope required. | Key custodian, key storage, domain separation, rotation, access review, and resolver design are not selected. HMAC references remain linkable within a scope. |
| Raw values leak through validation errors | Validator returns bounded error codes only; it does not echo values or paths. | Any future CLI/log wrapper must preserve that property. |
| Content leaks through hashes | Raw content and low-entropy identifier hashes are prohibited; payload hash covers only the allowlisted metadata object. | Until a non-secret configuration-manifest allowlist is approved, `agent_configuration_id` and `capture_configuration_id` must be null. |
| Behavioral inference from timing/counts | Bounded counts and event-level access restriction are required. | Timestamp precision, retention, report aggregation, and access policy remain open. |
| Legacy records become semantic evidence | V1/unknown schemas fail V2 validation; source rows remain immutable. | Promotion integration still needs an explicit Legacy exclusion regression test in WP3. |
| Schema-valid but false provenance | Source/task classification and persistence receipt are explicit fields. | JSON structure alone cannot prove runtime identity or receipt authenticity; producer integration and read-back are needed. |

## Migration and custody

- V1 records remain at the existing source location and are not rewritten, moved, backfilled, or assigned V2 semantics.
- No schema migration converts an old `level` or `capability_id` value into a measurement.
- V2 references are intended to use profile-scoped HMAC key versions. A key version is an identifier, never a key value. Rotation may accept multiple versions during a bounded transition, but must not silently re-key or merge profiles. No reference is authenticated by the current fixture validator.
- `agent_configuration_id` and `capture_configuration_id` remain null until an exact non-secret manifest input allowlist and its generation owner are approved. Arbitrary hashes in these fields are not accepted as metadata-only proof.
- A syntactically well-formed synthetic HMAC reference is accepted only as a fixture for structural validation. It does not demonstrate possession of a key, source authenticity, or receipt validity. `structural_disposition` returns a structural disposition only; no consumer or Promotion Gate may treat it as verified provenance.
- The accountable key owner is the user. macOS Keychain storage, profile-scoped key versioning, annual or incident/owner-change rotation, runtime root `/Users/yokapro/.hermes/runtime-evidence/agent-level/v2`, 60-day retention, and user-owned deletion authority are approved. Keychain implementation and source resolver remain open; only the root directory exists, no canonical DB has been created, and no key was read or created.

## Verification boundary

WP0/WP1 contract tests use synthetic fixture values only. The standard-library validator performs shape, cross-field, timestamp, payload-integrity, and size checks; HMAC reference validation is syntactic, not cryptographic. WP2 later added isolated Outbox, consumer, ACK, and transport-report fixtures using TemporaryDirectory databases. The latest 2026-10-21 Evaluator fixture run passed 172 tests with the Hermes virtualenv (standard Python: 172 tests, failures=0, errors=0, skipped=1); the macOS Hermes focused transport suite passed 52 tests with 1 Linux-only skip. Outbox and ledger 60-day purge primitives were exercised only on disposable fixture DBs. A current-tree cross-repository fixture E2E reached separate ACK receipt and report visibility while leaving `emitted` unknown for `independent_capture_denominator_not_implemented`; Draft 2020-12 validation was also run with `jsonschema 4.26.0`. These results do not connect the production Gateway, alter runtime configuration or LaunchAgent, collect live conversations, purge canonical data, or feed records to the Promotion Gate.
