# Current Evaluation Architecture and Migration Boundary

更新日: 2026-09-08
状態: migration design / runtime cutover not approved

## Purpose

This document is the navigation SSOT for the Agent Level evaluation migration.
It separates historical development checkpoints from current capability evidence.
It does not itself promote an Agent Level or authorize cron changes.

## Source-of-truth map

| Information class | SSOT | Authority |
|---|---|---|
| Current capability contract | `contracts/level-contracts.yaml` | Intended Level 1–9 gates |
| Evidence gate behavior | `scripts/promotion_gate.py` and `scripts/validate_stage1.py` | Executable validation/promotion rules |
| Legacy Phase history | `execution-evidence/2.3/`, `scripts/reclassify_phase23.py` | Historical development evidence only |
| Design decisions | `docs/decision-log.md` | Decision history and reversals |
| Current migration status | This document plus `scripts/audit_legacy_pipeline.py` | Cutover readiness only |
| Actual scheduled job | `/Users/yokapro/.hermes/cron/jobs.json` | External operational configuration; not changed by this repository branch |

## Explicit boundary

```text
Legacy Phase executor
  -> may produce development evidence
  -> must not determine current Agent Level
  -> must not update promotion status

Evidence Gate
  -> classifies Functional / Failure / Operational evidence
  -> computes a promotion candidate
  -> does not grant promotion without the approval gate

Cron cutover
  -> requires a clean audit, shadow validation, and explicit operational approval
```

## Current observed state

The cron-target repository `/Users/yokapro/Developer/agent-level-evaluator` is not a
cutover candidate. It still has the legacy `CHECKPOINTS.md` and
`scripts/progression_runner.py`, and it lacks the Evidence Gate runtime files.
The migration audit must return `blocked` for that repository.

This branch contains the Evidence Gate implementation and the migration audit, but
it intentionally retains legacy Phase files as historical material until a separate
migration change establishes the new runtime entrypoint.

## Cutover gates

Cron cutover is allowed only when all are true:

1. A single canonical repository and branch are selected.
2. The canonical runtime entrypoint does not call the legacy Phase executor.
3. Legacy Phase records are classified as historical/development evidence.
4. Functional, Failure/Recovery, and Operational evidence are stored separately.
5. Promotion remains blocked without the required evidence and human gate.
6. Shadow execution compares old and new results without duplicate side effects.
7. The scheduler configuration is reviewed and changed separately from repository code.

Until then, the correct status is `migration blocked`, not `Level progression`.
