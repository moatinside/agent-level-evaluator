# Completion Evidence Gate

## Status

- Status: implemented as an Evaluator-side deterministic validator
- Source pattern reviewed: Hermes PR #63625
- Scope: verify concrete completion evidence; do not trust self-assessment or an LLM judge as the final authority

## Adopted

```text
completion claim
  → declared conditions
  → evidence for each required condition
  → deterministic validation
  → passed / blocked / inconclusive
```

Supported required condition types:

- `command_exit_zero`
- `tests_pass`
- `artifact_present`

A completion result is `passed` only when every required condition has
verified deterministic evidence. Missing evidence is `inconclusive`, not pass.
Failed conditions and non-zero command exits are `blocked`.

## Deliberately not adopted

The reviewed source pattern contains fail-open behavior for judge failures,
unparseable judge output, and exhausted verification rounds. That behavior is
not compatible with this project's evidence gate. This implementation never
turns missing, malformed, or unavailable evidence into completion.

An LLM judge may be added later as a secondary review signal, but it cannot
override deterministic evidence or convert `inconclusive` into `passed`.

## Data boundary

The validator accepts references and bounded numeric results. It does not need
raw response text, session transcripts, or tool arguments. Evidence references
must be content-addressed (`artifact:sha256:<64 hex>`).

## Promotion boundary

This component proves completion-evidence validation mechanics only. It does
not prove that a task's conditions are well-designed, that the agent improved,
or that an Agent Level should be promoted. Those require an approved task
contract, independent review, and operational observations.
