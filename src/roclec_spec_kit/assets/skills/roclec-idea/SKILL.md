---
name: roclec-idea
description: Capture or evaluate FUT discovery with provenance, separate from approved change scope.
---

# Roclec idea

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Read existing FUT records and decisions. For capture, author a JSON record with model_schema, explicit FUT ID, source {location, locator}, finding, impact and questions; use `fut capture --file FILE`. Never reuse IDs, including discarded history. Use `fut decide ID --outcome evaluating|promoted|discarded|duplicate --actor NAME --reason TEXT [--target ID]` only for an authorized decision. Promoted/duplicate needs an existing compatible destination; promotion does not approve it. When a FUT is promoted to a change, capture its relevant text in the bundle and declare it as a `fut` origin. Import the draft before recording the FUT decision, then check the approve gate. Discoveries during implementation remain outside approved scope until an explicit change. Classify friction in the project flow (a gate that hinders, a role that underperforms, a stage that should run without AI) as a FUT with `"scope": "process"`; product discoveries keep `scope` product (the default). A person decides each, and a process FUT is addressed by revising the flow through `roclec-foundation`.
