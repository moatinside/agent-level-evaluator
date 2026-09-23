# Independent Shadow Evidence Verifier

## Purpose

Prevent the Agent Level shadow cron from treating an invalid Evidence record as successful when an LLM misses the validation error.

## Boundary

```text
cron (no_agent=true)
  -> run_shadow_evidence_guard.py
     -> run_shadow_batch.py
        -> trusted fixture producers/correction agent
     -> read only newly appended JSONL records
     -> validate_stage1.validate_evidence()
     -> integrity/raw-text/count/config checks
  -> stdout report + exit code
```

The script does not send external messages, promote a level, modify existing Evidence, commit, or push.

## Acceptance criteria

- A normal four-case run exits `0` and records `passed=2`, `blocked=1`, `inconclusive=1`, `failed=0`.
- Every newly appended record passes the existing Evidence validator, including the schema's closed-key boundary.
- Persisted JSON/JSONL records are revalidated before Promotion Gate consideration; malformed or invalid records are excluded from candidates and reported. Invalid records created by the current run fail the Guard.
- The evaluator configuration ID is a runtime SHA-256 manifest of the evaluator files and parameters.
- Integrity hashes are recomputed and match the persisted record.
- Raw response/body keys are absent.
- Any batch, parse, validation, count, identity, or integrity failure exits `1` and reports `CONTRACT_FAIL`.
- Existing records are retained; invalid records are never silently repaired or deleted.

## Failure semantics

The script's exit code is authoritative. A cron delivery may report the result, but the LLM is not part of the pass/fail decision. `0` means the changed path passed the deterministic checks; `1` means the run is not valid Evidence and promotion remains blocked.

## Configuration identity

The script computes `evaluator_configuration_id` from a canonical manifest containing the evaluator source files, contract/schema inputs, fixture cases, and execution parameters. This prevents a stale literal ID from surviving an evaluator change.

## Operational boundary

The first implementation is Shadow-only and writes to the existing daily JSONL path. The next scheduled run is required to verify the scheduler path; the manual isolated run proves only the script and local evidence path.
