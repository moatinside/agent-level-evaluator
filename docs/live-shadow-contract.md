# Live Shadow Policy Contract

## Status

- Status: accepted contract; fake Shadow adapter implementation under review
- Scope: Evaluator-side boundary for Hermes shadow/strict integration
- Repository: `moatinside/agent-level-evaluator`
- Current implementation branch: `feat/fake-shadow-e2e`
- Base: `39b38fe` (`origin/main`)

This document defines the callable contract between Hermes Gateway and the
Evaluator. It does not enable production delivery or claim live operational
evidence by itself.

## Responsibilities

### Hermes Gateway

- Supplies the completed response and bounded turn metadata.
- Decides whether the result is used in `shadow` or `strict` mode.
- In strict mode, withholds all assistant-content egress until an approval
  decision is returned.
- Does not supply executable commands in the request.

### Evaluator policy adapter

- Validates the completed response against an operator-owned evaluator policy.
- Returns a deterministic decision object.
- Returns an approved replacement only when validation passes.
- Returns `blocked` or `inconclusive` on failed, malformed, unavailable, or
  timed-out evaluation.
- Never sends a message to a platform.

### Evidence Collector

- Records metadata, hashes, statuses, bounded counts, and references.
- Does not persist draft text, correction text, or final response text.
- Separates shadow observation from strict delivery enforcement.

## Request contract

The adapter receives one JSON object over stdin or an equivalent in-process
call. The caller owns the transport and timeout.

```json
{
  "schema_version": 1,
  "request_id": "turn-20260906-0001",
  "final_text": "completed response supplied by Hermes",
  "metadata": {
    "platform": "discord",
    "chat_id_ref": "sha256:<64 lowercase hex>",
    "session_id_ref": "sha256:<64 lowercase hex>",
    "turn_id": "turn-20260906-0001",
    "agent_configuration_id": "sha256:<64 lowercase hex>",
    "evaluator_configuration_id": "sha256:<64 lowercase hex>"
  },
  "policy": {
    "required_patterns": [],
    "forbidden_patterns": []
  }
}
```

`final_text` is required for evaluation but is never written to the Evidence
ledger. Identifiers containing user or session identity must be references or
hashes, not raw personal identifiers.

The production adapter must not accept producer commands, correction commands,
shell fragments, or arbitrary URLs from this payload.

## Response contract

```json
{
  "schema_version": 1,
  "request_id": "turn-20260906-0001",
  "status": "passed",
  "allowed": true,
  "final_text": "approved response",
  "evidence_ref": "run:turn-20260906-0001",
  "reason": null,
  "attempt_count": 1,
  "correction_count": 0,
  "execution_mode": "shadow",
  "decision": "passed",
  "side_effect_status": "not_attempted",
  "evidence_persisted": true
}
```

Allowed result combinations:

- `passed`: `allowed=true`, `final_text` is a string.
- `blocked`: `allowed=false`, `final_text=null`.
- `inconclusive`: `allowed=false`, `final_text=null`.

Any other shape is treated by Hermes as `inconclusive`; it must not fall back
to unvalidated delivery.

## Mode semantics

| Mode | Evaluator called | Original response visible | Delivery authority |
|---|---:|---:|---|
| `legacy` | no | yes | existing Hermes path |
| `shadow` | yes | yes | existing Hermes path; decision is observation only; `side_effect_status=not_attempted` |
| `strict` | yes | no, until pass | Evaluator decision at final boundary; fail-closed on persistence failure |
| `production` | yes | according to approval | separately approved operational path |

A shadow result must never be reported as proof that delivery was blocked. A
strict result must never silently degrade to shadow or legacy when the adapter
is unavailable.

## Failure and timeout semantics

| Condition | Adapter result | Strict Gateway action | Evidence |
|---|---|---|---|
| Validator pass | `passed` | release approved final only | operational record |
| Validator failure with no correction | `blocked` | safe stop | negative evidence |
| Malformed policy result | `inconclusive` | safe stop | negative evidence |
| Evaluator exception | `inconclusive` | safe stop | negative evidence |
| Timeout | `inconclusive` | safe stop | negative evidence |
| Collector failure after decision | decision remains separate; report failure | do not change approval semantics | collector error record |

## Acceptance criteria

1. Valid requests produce schema-valid responses.
2. `passed` never returns a null or non-string `final_text`.
3. `blocked` and `inconclusive` never return replacement text.
4. Malformed output, exceptions, and timeout are fail-closed.
5. Raw response text is absent from persisted Evidence records.
6. The same request and fixed evaluator configuration produce the same decision.
7. Agent and evaluator configuration IDs are recorded for every run.
8. Shadow mode preserves the original delivery result and records the decision.
9. Strict mode provides the decision to Hermes without performing delivery.
10. No request field can select or execute an arbitrary command.

## Out of scope

- Enabling strict mode for the current Discord session
- Changing Hermes streaming behavior
- Real Discord E2E delivery
- Promotion to Operational Level 5
- Automatic policy changes based only on Evidence

Those require separate Hermes integration, shadow observation, independent
review, and human approval gates.
