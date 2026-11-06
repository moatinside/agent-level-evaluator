# Conversation evaluation decisions

## Evaluation stays separate from promotion

A model assessment is an input for human review. Human labels and causal review are stored separately. The rule is explicit: do not connect it to Level promotion. No evaluation result automatically changes an Evidence Gate, production state, or promotion status.

## External processing requires local opt-in

The repository contains no operator-specific channel allowlist. A local policy must explicitly enable the provider and list exact channel ID/name pairs. Missing, invalid, or disabled policy blocks live evaluation.

## Source text is not persisted

The evaluator may transmit compacted user/assistant content to the provider only under the enabled policy. New local evaluation, human-review, and correction-case artifacts retain controlled labels plus positions and character ranges; model- and human-authored free text, copied excerpts, and the full transcript are not persisted.

## Keep outputs outside the repository

Reports and automation state use local state directories. A path resolving inside the repository is rejected for live evaluation. Generated files and local policy are excluded from repository changes.

## Keep runtime boundaries explicit

This repository does not create a schedule, hook live Gateway traffic, or write to production/evidence systems. Those changes require a separate design, owner, authorization, and validation plan.

## Validate with synthetic data

Tests use synthetic conversations and mocked provider results. Passing tests proves only the tested local behavior; it does not prove live runtime operation, provider privacy, or operational readiness.
