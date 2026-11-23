---
name: roclec-implement
description: Implement an approved native Roclec change for one explicit component and record actual verification.
---

# Roclec implement

Run profile checks only in repositories you trust. `run verify` executes configured commands and retains raw output in local runtime logs. Review changed command arguments before executing a check.

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Before the implement gate, inspect the current digest and confirm a matching approval, complete foundation, exactly one release assignment for that same digest, and satisfied dependencies. An unpublished release containing an older intent revision must be replanned through `roclec-release`; do not start work or transfer its evidence. Then run `check --change ID --component NAME --gate implement`. Once it passes, reuse an existing start for the same digest and component, or record one with `change start ID --component NAME --actor ACTOR` if it is missing. A structured exit-1 gate such as `RELEASE_UNASSIGNED`, `REVIEW_REQUIRED` or `COVERAGE_MISSING` is an observed workflow blocker, not a tool crash; do not repeat the same command without changing an authorized precondition. Invalid invocation, IO failure or malformed output is a technical failure and must be reported separately. Read actual component instructions and approved contract/plan/design. Work within authorized scope and preserve unrelated changes. Execute meaningful checks with `run verify ID --component NAME --base EXPLICIT_REF --role ROLE --context CONTEXT`: ROLE is implementer (coordinator or human when that is who implemented) and CONTEXT is the actual session or tool identity doing the work, which a later review must not share. A passing run does not cover unspecified ACs or satisfy an enabled review policy. Record observations/imported results through evidence record without claiming they were executed by Roclec. Cite the stable keys of findings addressed in the implementation summary. A later reviewer determines whether they are fixed; do not record a finding resolution. New discoveries go to FUT or another explicit change. Do not edit current.json, integration/publication records or statuses; use native operations.

Deliver what `.roclec/flow.toml` declares in `deliverables` for stage `implement` (and `verify` when this role runs it). If the implement gate returns `CHECKPOINT_REQUIRED` for the declared `pre-implement` hook, stop and report the command in its remediation to the coordinator; never record the checkpoint or pass `--criteria` yourself.

When the flow requires session evidence for this stage, report your host and host session id to the coordinator, which records the session and cites it on `run verify` with `--session` (rule in `roclec-coordinator`).
