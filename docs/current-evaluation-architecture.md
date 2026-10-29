# Current Evaluation Architecture and Migration Boundary

更新日: 2026-10-28
状態: Evidence Gate実装済み・Production接続なし・v2会話レポートCronは10/29 09:00 JSTに一回限りの実行を予約、10/27・10/28の実評価は失敗

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
| Report-only v2 live-operation work plan | `docs/usable-first-plan.md` | One active plan for recovery, ordered work, and acceptance; local uncommitted worktree only |
| v2 feature implementation history | `docs/anthropic-insights-implementation-plan.md` | A–C design and 10/26 execution record, not current work order |
| Metadata-only Gateway/Outbox WP history | `docs/gateway-real-conversation-evaluation-work-plan.md` | Separate track, not a prerequisite for the report-only Cron |
| Measurement-first capability design | `docs/measurement-first-capability-design.md` | Observability-first entry gate for new capabilities and evaluation items |
| Migration audit | `scripts/audit_legacy_pipeline.py` | Legacy contamination and cutover-readiness check |
| Actual scheduled job | External scheduler configuration; job `35b6e4cf551e` | One-shot report-only v2 review at 10/29 09:00 JST; prior 10/27 and 10/28 failed, E2E unverified |
| Local real-conversation review | `scripts/run_conversation_review_cycle.py` and `conversation-review-output/` | Shared one-shot/scheduled v2 path; excluded from Promotion Gate |

## Start here

1. Read `AGENTS.md`.
2. Run `python3 scripts/evaluate_current_state.py` for the current Evidence state.
3. Run `python3 scripts/audit_legacy_pipeline.py --root .` for the legacy-boundary audit.
4. Run `python3 scripts/evidence_report.py --summary` for human-auditable Evidence results.
5. Run `python3 evals/run_evals.py` for skill-level structural checks.

Before connecting a normal Agent execution, review
`docs/evidence-runtime-contract.md`. It records the open contract decisions and
the Shadow acceptance matrix; it does not enable the connection by itself.

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
- Scheduler/cron change: report-only v2 job `35b6e4cf551e` was changed after explicit approval; no Production or Promotion connection

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

## Evidence quarantine boundary

Persisted Evidence has two operational states:

- **Active Evidence**: files under `operational-evidence/` and `evaluation-reports/` that pass the current Promotion Gate and may be considered for a promotion candidate.
- **Quarantined historical Evidence**: files under `evidence-quarantine/` that are retained byte-for-byte for audit and negative evidence but are excluded from current promotion assessment.

The quarantine directory must remain outside the active scan roots. Each quarantine migration is recorded in `evidence-quarantine/manifest.json` with the original path, destination path, record count, reason categories, and a SHA-256 file hash. `scripts/promotion_gate.py` audits the manifest and file hashes separately from active Evidence.

A current configuration rerun creates new Evidence; it does not repair, relabel, or delete historical records. Reports must show `records_considered`, `active_invalid_record_count`, `quarantined_historical_record_count`, and `quarantine_audit_status` as separate fields.

## Report-only scheduled conversation review v2

A new six-axis conversation review path is implemented in the `anthropic-insights-impl` worktree. It reuses the approved candidate selector and shared JST daily-trial ledger through `scripts/run_conversation_review_cycle.py`; direct evaluator CLI invocation is dry-run only. The existing report-only Cron and wrapper call this path and send Markdown stdout to the approved Discord channel. User authorization limits the next live run to 10/29 09:00 JST once; the job is configured one-shot.

One permitted v2 real-conversation evaluation was run. It produced `conversation-review-output/ec303c5c7254/evaluation.json` and `report.md`, with four `not_observable` axes and two `partial` axes. The initial question was unobservable and no question changes were extracted. Human calibration remains pending; this does not establish semantic accuracy or Agent improvement.

The path emits a versioned evaluation and trace report under `conversation-review-output/<evaluation_ref>/`. That directory is Git-ignored and is outside `promotion_gate.py` scan roots. Human calibration, comparison, and correction-case candidates stay in this directory. Correction cases require a recorded human `fail`; exports remain pending context review, approval, and execution.

The trace stores `observed_order`, `cause_hypothesis`, and human causal review separately. Sequence checks only validate references and ordering. They do not establish meaning or causality. Schema v1 five-axis comparisons remain separate from v2 six-axis model-to-human comparisons; unanswered axes remain pending and excluded from denominators.

Current boundary (2026-10-28): one local real evaluation was completed on 10/26 under the permitted daily limit. The shared trial ledger records 10/27 and 10/28 as `failed`, without a report name; those historical records do not contain a failure phase, so the exact cause remains unknown. The local worktree adds allowlisted `error_phase` / `error_code` propagation and backward-compatible ledger schema migration; the production ledger has not been migrated and no live provider or Cron run has exercised the repair. Five-module unittest history: 45 tests at the earlier P1 checkpoint, 58 after the prior P2 batch, 63 after the following fixes, and 66 after review-driven regressions (Python 3.11.15; exact command is in `docs/usable-first-plan.md`). The final review of snapshot `90bb4d3237501f98bb1908c287cf78996b2caab93527cf21752735148202c03c` returned `FINDINGS`: identifiers may pass through; unapproved message roles were included; success and dedupe state writes were separate; path operations retain a conditional TOCTOU risk; argparse errors could echo input. Local fixes now omit all non-user/assistant content and unknown role labels, atomically update the success/dedupe state, and sanitize argument errors. The user explicitly approved identifier transmission/persistence/delivery for the 10/29 run only. A conditional risk remains if another local actor mutates the output path concurrently; it is not hardened or runtime-tested. These post-review fixes and plan updates need a fresh static review before acceptance. The one-shot Cron `35b6e4cf551e` is enabled for 10/29 09:00 JST; actual provider evaluation, report readback, and Discord delivery are unverified. Real human calibration and correction-case creation remain pending. A successful evaluation is still one external evaluator vote, not a promotion, production, or generalized Agent improvement result.

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

Production or normal-Agent runtime cutover
  -> separate change
  -> requires explicit operational approval
  -> is not implied by repository readiness
```

## Production and normal-Agent runtime cutover gates

A Production connection or a normal-Agent runtime cutover requires all of the following:

1. A single canonical repository and branch are selected.
2. The canonical runtime entrypoint does not call a legacy Phase executor.
3. Legacy Phase records are classified as historical/development evidence.
4. Functional, Failure-Recovery, and Operational evidence are stored separately.
5. Promotion remains blocked without the required evidence and human gate.
6. Shadow execution has been reviewed for duplicate side effects and environment separation.
7. Any scheduler for the Production or normal-Agent runtime is reviewed and changed separately from repository code. The report-only evaluator Cron is a separate read-only review path.

Until separate operational approval is recorded for a Production or normal-Agent runtime cutover, the status is:

```text
Evidence Gate implemented
report-only v2 review Cron approved and configured
Production / normal-Agent runtime cutover not enabled
automatic promotion disabled
```
