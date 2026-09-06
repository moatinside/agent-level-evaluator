# Hermes pre-delivery integration design

## Status

- Status: proposed, not connected
- Evaluator implementation: `/Users/yokapro/Developer/agent-level-evaluator-level-gates`
- Hermes source: `/Users/yokapro/.hermes/hermes-agent`
- Hermes branch inspected: `main`
- Hermes working tree: pre-existing user changes; do not overwrite

## Confirmed current path

The current Gateway path creates `GatewayStreamConsumer` in `gateway/run.py`, assigns its `on_delta` to `agent.stream_delta_callback`, and calls `finish(final_text)` after `run_conversation()` returns. `GatewayStreamConsumer` progressively sends or edits platform messages while deltas arrive. Its existing `on_before_finalize` callback is used for pre-finalize housekeeping (for example, pausing typing), not for replacing the final answer with a validated answer.

Therefore, validating only from `on_before_finalize` is insufficient for strict validation: prior stream deltas may already be visible.

## Target policy

Strict validation is opt-in per response policy and must preserve legacy behavior when disabled.

```text
agent generation
  -> hold response in memory (no external text delivery)
  -> validate complete final response
  -> correction agent, if blocked and configured
  -> validate corrected response again
  -> allow one final platform delivery OR safe stop
```

For strict validation, `GatewayStreamConsumer.on_delta` must not send progressive content. The consumer may still receive deltas for internal buffering, TTS policy must be explicitly decided, and tool-progress messages must not leak unvalidated answer text.

## Proposed boundary

Add a generic pre-delivery policy interface in Hermes, without embedding the evaluator repository or its business logic into the Hermes core.

```python
class PreDeliveryDecision(TypedDict):
    allowed: bool
    final_text: str | None
    status: Literal["passed", "blocked", "inconclusive"]
    evidence_ref: str | None

class PreDeliveryPolicy(Protocol):
    async def evaluate(self, *, final_text: str, metadata: dict) -> PreDeliveryDecision: ...
```

The policy should be injected into the gateway turn context/configuration. The policy must not receive arbitrary executable commands from the user message. Configuration belongs in `config.yaml`; secrets remain in the protected secret mechanism.

## Integration point

The policy runs after the agent has returned a genuinely completed `final_response` and before any final external send. The existing `finish(final_text)` call should receive the policy-approved text, not the unvalidated text.

For strict validation:

1. Disable progressive external answer delivery for this turn.
2. Preserve the complete final response in the turn context.
3. Call the policy once at the final-response boundary.
4. On `allowed=true`, send the approved final response exactly once through the normal adapter path.
5. On `allowed=false`, do not call the final answer send path; emit only a safe, non-sensitive stop notice if configured.
6. Record only metadata and references through the Evaluator Collector adapter.

## Transport modes

| Mode | Delta visibility | Final policy | Intended use |
|---|---|---|---|
| `legacy` | progressive | none | current compatibility behavior |
| `shadow` | progressive | observe only, never alter delivery | calibration and evidence collection |
| `strict` | buffered, invisible | allow or stop | Level 5 delivery gate |

`shadow` must never be reported as delivery enforcement. `strict` must not silently fall back to legacy delivery if the Validator is unavailable; it must stop or return `inconclusive`.

## Required failure behavior

- policy timeout: no unvalidated answer delivery; safe stop and evidence
- policy exception: no unvalidated answer delivery; safe stop and evidence
- correction-agent failure: no unvalidated answer delivery; safe stop and evidence
- invalid policy result: treat as `inconclusive`; no delivery
- session becomes stale: abandon the turn; do not deliver stale text
- platform send failure after approval: record delivery failure separately; do not claim user receipt

## Acceptance criteria

1. Legacy mode passes existing streaming tests without behavior change.
2. Shadow mode records policy outcomes but does not change the visible answer.
3. Strict mode never exposes a delta before policy approval.
4. Strict pass sends only the policy-approved final response.
5. Strict block and inconclusive paths send no answer text.
6. Policy timeout, exception, malformed result, and correction failure are safe stops.
7. Existing session, tool-progress, interruption, and stale-turn behavior remains intact.
8. Tests run against a temporary Hermes home and a fake adapter; no real Discord message is sent.
9. Evaluator Evidence records contain metadata and references only; no raw response text.

## Scope boundary

This document defines the integration contract only. It does not yet modify `/Users/yokapro/.hermes/hermes-agent` because that worktree contains unrelated uncommitted changes on `main`. The next implementation must use a separate Hermes feature worktree or branch based on the inspected commit, then add focused tests before any gateway restart or production-like delivery test.
