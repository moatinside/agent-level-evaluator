# External conversation evaluator: implementation specification

## Objective

Provide a tightly bounded local workflow for evaluating one explicitly selected conversation through the Claude Code CLI. The implementation must fail closed when external processing is not explicitly enabled, keep source-message text out of persisted artifacts, and keep model assessment separate from human review and promotion.

## Components

- **Policy loader:** Reads an operator-owned local JSON policy. Requires an explicit enable flag, the supported provider/payload identifiers, and exact channel ID/name pairs. Rejects missing, malformed, wildcard, or duplicate entries.
- **Candidate selector:** Opens the local session database read-only and selects only completed, visible, non-archived sessions matching the exact policy pair and configured size/time limits. Processed references and attempt counts are kept in a separate local state database.
- **Input minimizer:** Sends only compacted user/assistant messages. Tool output, session metadata, and other roles are omitted; common identifier patterns are redacted. This is defense in depth, not a guarantee of full anonymization.
- **Provider boundary:** Invokes the configured CLI with tools/custom integrations disabled and session persistence disabled. No provider call occurs in dry-run or when policy is missing, invalid, or disabled.
- **Result validator:** Requires the closed evaluation shape, known axis/status labels, valid message positions and bounded character ranges. Durable output replaces model-authored prose with fixed labels and stores positions/ranges, not excerpt text.
- **Artifact writer:** Writes reports and state outside the repository with restrictive local permissions, verifies read-back, and emits only sanitized status and relative report references.
- **Human review tools:** Keep reviewer labels, causal review, comparisons, and correction-case candidates separate. Correction cases retain position/range references, not copied conversation excerpts. Candidate cases are not executed or approved automatically.

## Acceptance criteria

1. Missing or invalid local policy blocks the cycle before provider invocation.
2. A disabled policy permits dry-run selection but blocks live evaluation.
3. Only exact allowlisted channel pairs can be selected.
4. Any output or state path under the repository blocks live evaluation.
5. Unknown CLI arguments and provider failures do not echo argument values, local paths, provider output, or conversation text.
6. Persisted evaluation and correction-case schemas reject excerpt fields.
7. Synthetic tests verify the generated artifacts contain no source-message body, transcript, prompt, or excerpt.
8. No scheduler, Gateway runtime, production, or Evidence Gate state is modified by this implementation.

## Operational limits

The redaction rules are incomplete; the compacted user/assistant input sent to an enabled provider may still disclose context. Operators remain responsible for confirming authorization for provider transmission. Automated tests use synthetic inputs and mocked provider responses; they do not certify external-provider privacy or establish that a live route is configured.
