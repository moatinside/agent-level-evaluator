# Gateway Runtime Evidence — source map and ownership decision

- Date: 2026-10-20
- State: WP0 evidence map complete; canonical runtime-ledger decision remains open
- Scope: static code and metadata-only inventory; no live Gateway, settings, or scheduled job changes

## Repository state preserved

- Evaluator source: detached worktree at `b3583a9` under `agent-level-evaluator-worktrees/runtime-evidence-v2`. The existing `main` worktree and its untracked plan document were left unchanged.
- Hermes source: branch `work/agent-level-runtime-evidence` has pre-existing uncommitted changes. Relevant paths are `gateway/config.py`, `gateway/evaluator_shadow.py`, `gateway/run.py`, `gateway/run_turn.py`, `tests/gateway/test_evaluator_shadow_config.py`, and untracked `tests/gateway/test_evaluator_shadow_runtime.py`. These files were inspected read-only and not modified. Other dirty/untracked paths were left untouched.
- A checkout's source code is not evidence that a running Gateway loaded that code. Process identity and loaded configuration were not established in this work package.

## Current path and boundaries

| Stage | Source observed | What it establishes | What it does not establish |
|---|---|---|---|
| Opt-in construction | Hermes `gateway/run.py::_init_evaluator_shadow`; `gateway/config.py::EvaluatorShadowConfig` | Adapter construction requires explicit enablement; runtime capture is restricted to Shadow plus configured platform and chat-reference scopes. | That current settings enable capture or that a running process loaded this checkout. |
| Canonical persistence | Hermes `agent/turn_finalizer.py::finalize_turn` | `persistence_confirmed` becomes true only after `_persist_session` returns true; unavailable, false, or exception paths do not mint that confirmation. | An independent receipt identifier suitable for consumer read-back. |
| Observer candidate | Hermes `gateway/evaluator_shadow.py::EvaluatorShadowAdapter._evaluate_sync` | Existing code requires capture enabled, in-scope platform/chat, confirmed persistence, a completed turn, and a non-empty final response. | Coverage of failed/interrupted/skipped events or a durable outbox. |
| Current reference handling | Same adapter | References are SHA-256 digests of raw chat/session/event identifiers. The completed response is passed to the evaluator subprocess in memory. | V2 keyed-reference privacy, key custody, or consumer ACK. Plain SHA-256 does not meet the proposed V2 reference contract. |
| Gateway seam and egress | Hermes `gateway/run_turn.py::_run_agent_apply_pre_delivery_gate` and `_run_agent_release_stream_consumer` | The optional gate seam is before stream release. A separate Strict path exists in source. | That Strict is enabled; this plan does not enable or test it against a live service. |
| Existing capture sink | `~/.hermes/runtime-evidence/agent-level/live-shadow.jsonl` | A metadata inventory is recorded in `docs/legacy-gateway-shadow-manifest.json`. | Per-row proof that a normal user conversation generated it, or semantic capability measurement. |
| Existing Evaluator adapter | `scripts/hermes_shadow_adapter.py` | Isolated adapter accepts a completed-response event and writes the existing assessment-evidence format. | A V2 envelope consumer, Outbox, read-back ACK, or live Gateway connection. |
| Existing trajectory runner | `scripts/run_real_conversation_shadow.py` | A separate sanitized-case runner exists. | It does not consume the Gateway JSONL as its event stream. |
| Active report scan | `scripts/promotion_gate.py::_iter_paths` | Only `<root>/operational-evidence` and `<root>/evaluation-reports` are scanned; default eligible environments are production-like/production. | The external Gateway JSONL is not part of this report path. |
| Scheduled structural checks | External LaunchAgent invokes the blue `evals/run_evals.py` path, per prior read-only inspection | This is a skill-structure check, not a Gateway-event consumer. | Runtime conversation evaluation. No scheduler state was changed here. |

`evidence_report.py --summary` currently scans one file/line, rejects one record, and includes zero eligible records. The only scanned file is the historical `evaluation-reports/phase23-reclassification-20260906.json`; it lacks `evidence_class` and is rejected by the current collector. This is not Gateway JSONL consumption.

The existing producer also assigns the fixed `level=5` and `capability_id=self_reflection` labels through `live_shadow_policy.py`. Those are not measured outcomes and are excluded from V2.

## Legacy inventory

The manifest records only file-level integrity metadata, field presence, timestamps, and aggregate enum counts. No evidence rows, raw IDs, or text values are included. The source file was not moved, edited, or deleted. `integrity_hash_present=119` means the field is present; this work package did not re-verify each row's integrity hash.

## Canonical ownership decision

`docs/current-evaluation-architecture.md` identifies the Evaluator repository as the current Evidence Gate and promotion-policy owner. The Gateway JSONL is outside its active scan roots. On 2026-10-21 the user selected canonical runtime root `/Users/yokapro/.hermes/runtime-evidence/agent-level/v2`, 60-day retention, user-owned deletion, and the user as HMAC-key owner; only the root directory exists, and no canonical DB or Keychain key has been created.

**Selected local policy:** Evaluator owns the V2 contract, consumer, ledger semantics, and reports. Runtime records remain outside the source tree under the explicitly approved data root. The user owns retention and the profile-scoped key. The local root, 60-day retention, directory/DB modes, Keychain choice, and key-rotation policy are approved; canonical DB use, Keychain implementation/custody, and remote-journal destination/retention are still pending.

## Non-migration rule

The 119 V1 records remain byte-for-byte in their current location and are classified as legacy transport observations. They are not converted into V2, included in semantic evaluation, or used by the Promotion Gate. A record is accepted by the proposed runtime contract only if it validates as `schema_version=2` and `event_type=turn_settled`; older or unknown formats fail closed.

## Supplemental candidate-branch trace — 2026-10-21

This read-only source trace inspected `/Users/yokapro/Developer/hermes-worktrees/runtime-evidence-wp2`, branch `feat/runtime-evidence-outbox` at its local checkout. It is distinct from the older Hermes worktree inventory above. No Gateway/config changes, service runs, remote writes, or tests were part of the trace.

| Boundary | Current source path | Acceptance consequence |
|---|---|---|
| Ingress | `gateway/run_inbound.py::_handle_message` → `gateway/run_turn.py::_handle_message_with_agent` → `_run_agent` | A location exists to resolve channel/profile scope; no V2 capture or one-event pilot guard is wired. |
| Finalized turn | `agent/turn_finalizer.py::finalize_turn` calls `_persist_session`; it reports `persistence_confirmed` only as a boolean after a positive return. | V2 requires a verifiable persistence receipt reference. No production receipt ref was found; the symbol occurs only in the Outbox test fixture. |
| Result handoff | `gateway/run_turn_runner.py::run_sync` maps the finalizer result into a smaller result. | `persistence_confirmed` and `turn_exit_reason` do not pass through this handoff. `agent_persisted` is a duplicate-write skip flag, not persistence evidence. |
| Gateway output | `gateway/run_turn.py::_run_agent_inner` receives the result, applies the optional pre-delivery gate, then releases streaming output. | This is a usable ordering seam, but it is not an Observer integration or persistence-receipt proof. |
| Existing shadow | `agent/conversation_loop.py::run_conversation` uses `start_runtime_shadow`/settlement for State Answer Shadow. | Its explicit collector and `input_unavailable` contract are not V2 envelope/Outbox transport. Reuse of lifecycle pattern would require new V2 contract and tests. |
| Existing hooks | `agent/turn_finalizer.py::_emit_post_llm_call` runs only for persisted, non-empty, non-interrupted responses and carries user/assistant text/history. Gateway `agent:end` also includes response text. | Neither hook is a metadata-only all-outcomes capture point. |
| Evaluator Shadow | `gateway/config.py::EvaluatorShadowConfig` defaults disabled; `gateway/run.py::_init_evaluator_shadow` constructs it only under complete opt-in. `gateway/evaluator_shadow.py::_evaluate_sync` sends final text to the local Evaluator CLI. | This is a separate content-bearing evaluation flow, not the V2 metadata-only transport. It must not be used as an implicit substitute. |
| V2 Outbox | The candidate `gateway/runtime_evidence_outbox.py` is referenced only by itself and its candidate test. | It is not wired into Gateway runtime. Its local SQLite cannot independently count an event that the same host volume cannot retain. |
| R2 budgeted journal boundary | Hermes `gateway/runtime_evidence_r2_transport.py`, `gateway/runtime_evidence_r2_s3.py`, and focused tests | The injected S3 adapter enforces `IfNoneMatch="*"`, single-attempt settings, bounded read-back, and access through the local budgeted journal; one user-authorized adapter smoke observed a Keychain read and exact-byte PUT/GET for a synthetic object. | It is not wired to Gateway or Outbox consumer; the single-operation authorization does not permit repeating the provider request and does not prove runtime integration, repeated reliability, or account-wide billing limits. |
| Shared telemetry | Hermes shared-metrics defaults collection and send off; its relay uses bounded aggregate metrics and a configured HTTPS endpoint. | No project contract designates that endpoint as V2 journal storage; it is not an approved independent denominator. |

**Result:** no real Gateway→V2 Observer→Outbox/consumer→report path is wired. A local Outbox fixture or a fake sink can prove component behavior, not capture completeness under host-volume exhaustion. Local retention policy and Outbox/ledger fixture purge primitives exist; canonical DB purge is unrun. The test target is Cloudflare R2 bucket `agent-level-runtime-evidence-v2`; one user-authorized adapter-level PUT/GET was executed and reported exact-byte read-back. The authorization was limited to that synthetic smoke and does not permit repeated requests. Treat it only as a provider-path observation, not as proof of runtime integration or repeated reliability. Durable journal integration, remote retention, consumer ACK/report read-back, HMAC-key custody, and Gateway wiring remain incomplete. The smallest compliant implementation must preserve the real finalized result/receipt through `run_sync`, capture metadata-only evidence for all terminal outcomes exactly once, use the Outbox only as local staging, and prove the end-to-end journal on macOS before claiming the host-volume denominator.
