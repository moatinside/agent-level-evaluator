# Current Evaluation Architecture and Migration Boundary

更新日: 2026-09-09
状態: Evidence Gate実装済み・Production/cron切替は未実施

## Purpose

This document is the navigation SSOT for the Agent Level evaluation system.
It defines the current evaluation path, the boundary from the legacy Phase system,
and the separate approval required for scheduler or production changes.

It does not itself promote an Agent Level, enable automatic promotion, or authorize
scheduler changes.

## Source-of-truth map

| Information class | SSOT | Authority |
|---|---|---|
| Current capability contract | `contracts/level-contracts.yaml` | Intended Level 1–9 gates |
| Evidence Gate behavior | `scripts/promotion_gate.py` and `scripts/validate_stage1.py` | Executable validation and promotion-candidate rules |
| Current state observation | `scripts/evaluate_current_state.py` | Read-only current Evidence and blocker report |
| Legacy Phase history | `archive/legacy-phase/` and `evaluation-reports/phase23-reclassification-20260906.json` | Historical development evidence only |
| Design decisions | `docs/decision-log.md` | Decision history and reversals |
| Migration audit | `scripts/audit_legacy_pipeline.py` | Legacy contamination and cutover-readiness check |
| Actual scheduled job | External scheduler configuration | Separate operational configuration; not changed by this repository |

## Start here

1. Read `AGENTS.md`.
2. Run `python3 scripts/evaluate_current_state.py` for the current Evidence state.
3. Run `python3 scripts/audit_legacy_pipeline.py --root .` for the legacy-boundary audit.
4. Run `python3 scripts/evidence_report.py --summary` for human-auditable Evidence results.
5. Run `python3 evals/run_evals.py` for skill-level structural checks.

## Current state

The canonical repository is the current `main` branch. The Evidence Gate runtime
and its tests are present, and the legacy Phase executors are under
`archive/legacy-phase/` rather than being current entrypoints.

The current read-only evaluator reports:

- Evidence assessment: `unassessed` when no eligible production-like Evidence is present
- Automatic promotion: disabled
- Human promotion gate: required
- Legacy Phase executors: not invoked by current evaluation
- Production connection: not enabled
- Scheduler/cron change: requires separate operational approval

A successful migration audit means that the repository is technically prepared for
a separately reviewed cutover. It does not mean that a scheduler has been changed
or that production execution has started.

## Phase 2.3 boundary

Phase 2.3 is retained as historical development evidence. Its old executor,
execution plan, and checkpoint material are archived under `archive/legacy-phase/`.
Its results are not current Agent Level evidence and must not be used as a direct
Level-promotion basis.

The reclassification record is:

```text
evaluation-reports/phase23-reclassification-20260906.json
```

## Explicit boundary

```text
Legacy Phase material
  -> historical development record
  -> may be inspected or reclassified
  -> must not determine current Agent Level
  -> must not update promotion status

Evidence Gate
  -> validates Functional / Failure-Recovery / Operational evidence
  -> computes a promotion candidate
  -> does not grant promotion without the human gate

Production or scheduler cutover
  -> separate change
  -> requires explicit operational approval
  -> is not implied by repository readiness
```

## Cutover gates

A production or scheduler cutover requires all of the following:

1. A single canonical repository and branch are selected.
2. The canonical runtime entrypoint does not call a legacy Phase executor.
3. Legacy Phase records are classified as historical/development evidence.
4. Functional, Failure-Recovery, and Operational evidence are stored separately.
5. Promotion remains blocked without the required evidence and human gate.
6. Shadow execution has been reviewed for duplicate side effects and environment separation.
7. The scheduler configuration is reviewed and changed separately from repository code.

Until a separate operational approval is recorded, the correct status is:

```text
Evidence Gate implemented
runtime cutover not enabled
scheduler change approval required
automatic promotion disabled
```
