---
name: roclec-ux
description: Specify AC-linked interaction behavior for an approved native capability/change with user-facing scope.
---

# Roclec ux

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Inspect the explicit change and component design references. Describe actors, navigation, meaningful states, permissions, errors, recovery, accessibility and platform behavior using existing AC IDs. Keep criterion text only in its contract snapshot. Use existing design authority and applicable consumer-pinned skills; public marketing pages and application screens may need different methods. Preserve existing product documents. Store supporting UX at consumer-owned paths and pin the applicable reference when it changes approved behavior. Ask for unresolved material interaction choices; do not infer prototype approval or create an additional product source.

Deliver the stage `design` `deliverables` declared in `.roclec/flow.toml`. UX is not approval: the design checkpoint is recorded by the person through `checkpoint PATH --outcome approved|rejected --digest SHA --actor ACTOR --reason TEXT --criteria FILE`, where FILE holds their evaluation of the design point's criteria.
