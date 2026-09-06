# Experience Ledger Adoption

## Scope

This is an Evaluator-side adoption of the reusable experience pattern reviewed
in Hermes PR #91519. It records what happened during an evaluated task without
turning storage into proof of improvement or Agent Level promotion.

## Lifecycle

```text
execution metadata + outcome + evidence reference
  → deterministic record validation
  → pending experience record
  → human approval / rejection
  → approved retrieval for the same task and configuration
```

## Boundaries

- Raw prompts, responses, transcripts, and tool arguments are not stored.
- A lesson is represented by a content hash plus a bounded, redacted summary
  so approved retrieval can provide a reusable hint without retaining raw
  execution text.
- Approval requires an actor reference, reason reference, and timestamp.
- Duplicate `experience_id` values are rejected.
- `pending`, `rejected`, and `obsolete` records remain auditable but are not
  returned by retrieval.
- Retrieval is constrained to the same `task_ref` and `configuration_id`.
- Experience accumulation does not prove agent improvement or justify Level
  promotion.
- LLM judgment is not required for record validity and cannot turn malformed
  or missing evidence into a valid record.

## Adopted from #91519

- Task execution can produce a reusable experience record.
- Experience has provenance, outcome, and retrieval boundaries.
- The ledger is a separate layer from runtime response generation.

## Deliberately not adopted

- Automatic self-improvement or mutation.
- Automatic approval of lessons.
- Cross-configuration inheritance of experience.
- Treating the number of stored experiences as an effectiveness metric.

Effectiveness requires later shadow observations, approved retrieval usage, and
before/after regression evidence. Those are separate work.
