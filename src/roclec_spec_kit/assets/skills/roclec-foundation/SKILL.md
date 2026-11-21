---
name: roclec-foundation
description: Establish or revise agreed product, engineering and design references for native Roclec components.
---

# Roclec foundation

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Inventory existing context, principles, architecture/stack, engineering, verification, operations and applicable design authorities. Map existing documents rather than creating duplicate truths. Distinguish proposals, agreements and unresolved decisions, with actor/reason and source hashes. Register sources with `reference add ID --path PATH --component NAME --role ROLE` or `reference update`. Record an actual agreement with `foundation agree --ref ID --actor ACTOR --reason REASON`. For user-facing design consult consumer-pinned design skills when relevant; restore only an existing consumer skills-lock.json when authorized, without guessing a stack. Run `foundation check --component NAME [--change CHG-ID]`. A passing existence/hash check does not certify semantic sufficiency; resolve material gaps before implementation.

Inventory existing architecture decisions too. Register each ADR file under the profile's `[adr]` folder (default `docs/adr/`) as it is, with `reference add ADR-NNN --path PATH --component NAME --role decision [--supersedes ADR-MMM]`; do not rewrite it into the template. An ADR's state (proposed, accepted, stale, superseded) is derived: read it with `list adrs` or `inspect --adr ADR-NNN`. Only `foundation agree --ref ADR-NNN` with the user's real actor accepts one, and only after the user decided it. ADRs are not foundation roles that every component needs, and they are not `.roclec/decisions/`, which holds approvals and agreements.
