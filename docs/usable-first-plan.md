# Conversation review: operator workflow

## Goal

Run a bounded evaluation only for an operator-selected conversation, preserve enough evidence coordinates for a reviewer to revisit the source when authorized, and keep conversation text out of generated files.

## Before enabling external evaluation

1. Confirm the intended account, exact channel ID/name pair, provider, and permitted payload with the data owner.
2. Create the operator-owned policy file in the local state directory. It must contain the required policy fields; do not commit it, paste it into tickets, or include it in diagnostics.
3. Keep `external_evaluation_enabled` false while checking the local configuration. The policy must use the supported provider and payload labels and an exact, non-wildcard channel pair.
4. Review the data-minimization behavior. Common URLs, email addresses, phone numbers, local paths, and credential-like strings are filtered, but the filter is not complete anonymization.
5. Obtain explicit authorization before setting the policy to enable external processing. The policy is a persistent opt-in; disabling it blocks the automated route.

## Run sequence

- Use `python3 scripts/run_conversation_review_cycle.py --dry-run` to check whether the configured selector finds a candidate. Dry-run does not call the provider.
- A run without `--dry-run` can send the selected, compacted user/assistant content to the configured provider. Run it only after the policy and authorization are confirmed.
- The automation selects at most one eligible conversation per configured JST day and records deduplication state locally.
- Reports and state are written under the user's local state directories, never under the repository. Command output contains a report reference, not an absolute home-directory path.

## Stored output

Generated records contain evaluation labels, fixed privacy-safe labels, and evidence positions/character ranges. Model- and human-authored free text is not written to new records; source-message excerpts and the full transcript are also excluded.

A human reviewer may consult the original source only if independently authorized. The record itself does not reproduce the message text. Human labels and causal review remain separate from model output; no automatic promotion or production decision is made.

## Stop conditions

Stop without provider invocation if the policy is missing or invalid, external evaluation is disabled, output/state paths resolve inside the repository, the daily limit is reached, the candidate is outside the allowlist, or a validation/read-back check fails. Do not retry a failed evaluation automatically or switch to another conversation to obtain a result.

## Acceptance checks

- Synthetic tests pass for allowlist, opt-in, output-path, schema, and failure-handling behavior.
- A synthetic end-to-end evaluation proves the generated JSON and Markdown contain no source-message body or excerpt.
- Repository and public diff scans find no operator policy, local path, channel identifier, conversation report, or unverified run record.
- Scheduler state is not changed by this repository workflow.
