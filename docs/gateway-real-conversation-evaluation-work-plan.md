# Gateway conversation evaluation: integration boundary

## Current repository scope

The evaluator is a local, policy-gated batch workflow over an existing session database. It reads the database in read-only mode, uses an explicit operator-owned allowlist, and writes local review artifacts outside the repository. This repository does not install a Gateway hook, capture live traffic, modify delivery behavior, or create a recurring schedule.

## Data handling

When an operator explicitly enables external evaluation, compacted user/assistant content may be sent to the configured provider. Tool output, session metadata, and other roles are omitted, and common identifiers are redacted. These filters are incomplete. New persisted evaluation and correction-case artifacts contain controlled labels and evidence coordinates only; model- and human-authored free text, transcript text, and copied excerpts are not persisted.

## Future integration is separate work

A future Gateway/runtime integration would require a new design covering:

- the responsible owner and authorization for each data source;
- the minimum event and content fields required for a stated evaluation question;
- explicit opt-in and a fail-closed disable path;
- retention, access control, deletion, and incident response;
- separation from evidence promotion, production routing, and user-visible delivery;
- synthetic boundary tests followed by an independently approved runtime probe.

No runtime collector, scheduler, gateway behavior, production path, or Evidence Gate transition is authorized by this document. It is a boundary and planning note, not a claim that such integration is implemented or active.
