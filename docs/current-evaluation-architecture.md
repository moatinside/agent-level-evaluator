# Conversation evaluation architecture

## Purpose

The evaluator produces a structured, human-reviewable assessment of a selected local conversation. A model result is an observation to review; it does not establish facts about a user or authorize promotion, production use, or an Evidence Gate transition.

## Data flow

1. The selector reads the local session database in read-only mode.
2. A candidate must match an operator-configured channel ID and display-name pair, be within the configured lookback window, and pass the size and duplicate limits.
3. Before evaluation, the transcript is compacted. Tool output, session metadata, and unapproved roles are omitted; common identifiers are redacted. These filters reduce exposure but do not guarantee anonymization.
4. External evaluation is blocked unless a valid local policy explicitly enables the provider and names at least one exact channel pair. No channel allowlist is embedded in the repository.
5. The evaluator runs with tools and custom integrations disabled and session persistence disabled. Conversation content is transmitted to the configured external provider only when the operator has enabled that route.
6. Local artifacts are stored outside the repository. They contain scores, fixed privacy-safe labels, and evidence positions/character ranges. Model- and human-authored free text, message excerpts, and the full transcript are not written to new artifacts.
7. Human review remains a separate record. Pending review stays pending; the model result does not make a promotion decision.

## Guardrails

- Missing, malformed, or disabled policy fails closed.
- Channel matching uses an exact ID/name pair; wildcard channel names are rejected.
- Database reads are read-only. Evaluation state and reports are kept outside the repository.
- CLI errors and status output avoid printing conversation text, raw session identifiers, and absolute report paths.
- Existing reports with embedded message text are not treated as valid sanitized output by the automatic route.
- This repository does not create or modify a scheduler. Any scheduler is separately managed and requires its own authorization and verification.

## Scope boundaries

This code does not instrument live Gateway traffic, write to production systems, promote an agent, or connect an evaluation to an Evidence Gate. Any such integration requires a separate design and explicit approval.

## Verification

The automated tests use synthetic sessions and stubbed provider responses. They verify policy gating, candidate selection, output validation, and that persisted artifacts omit source-message bodies. They do not run a live evaluation or prove that external provider processing is risk-free.
