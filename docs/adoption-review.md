# Contributor Pattern Adoption Review

## Scope

This is a working adoption record. It does not change the canonical Level
contracts until the adopted mechanisms have independent evidence in this
Evaluator project.

## Reviewed candidates

| Source | Observed mechanism | Decision | Reason |
|---|---|---|---|
| Hermes PR #75932 | trace → sanitized candidate → human approval → deterministic scoring → regression corpus | Adopt now | Directly strengthens reproducible evidence and prevents self-grading from becoming a regression case |
| Hermes PR #63625 | completion gate based on post-task evidence | Adopt next | Useful for separating response quality from actual task completion; requires a separate artifact contract |
| Hermes PR #91519 | experience ledger and explainable retrieval | Adopt as Level 2 candidate | Relevant to experience reuse, not a Level 5 delivery gate; keep capability boundary separate |
| Hermes PR #61645 | autonomous evaluation and self-modification engine | Partial only | Retain failure taxonomy and regression ideas; do not adopt claimed statistics or autonomous mutation without independent evidence |
| Hermes PR #77236 | LLM mutation with rollback and regression gates | Partial only | Rollback and regression are useful; automatic Skill mutation remains disabled pending approval and operational proof |
| Hermes PR #76350 | durable branch → experiment → evaluate → merge/revert loop | Defer | Appropriate to Level 7 environment improvement, not the current Level 5 scope |

## Adopted now: trace-derived evaluation candidate

The first implementation is intentionally narrow:

```text
session trace
  → redact secrets, URL credentials, and local paths
  → retain bounded structural metadata and hashes
  → status=candidate
  → human approval remains required
  → later deterministic scoring / regression use
```

The implementation does not:

- auto-approve a candidate;
- persist raw prompt, outcome, trace excerpt, session ID, tool arguments, or local path;
- infer market or capability level from one trace;
- execute a tool or command from a trace;
- change a Level contract automatically.

## Acceptance criteria for promotion

1. Candidate output validates against `schemas/evaluation-candidate.schema.json`.
2. Sanitization tests cover secret-like values, URL credentials, and local paths.
3. Candidate status remains `candidate` until an explicit human decision.
4. A later scorer refuses unapproved or unsanitized candidates.
5. At least one real shadow batch produces candidates without raw-text persistence.
6. Rejected candidates remain available as negative evidence and are not silently deleted.

## Evidence boundary

The candidate generator proves sanitization and lifecycle mechanics only. It
does not prove that the underlying task is representative, that the agent
improved, or that a Level promotion is justified.
