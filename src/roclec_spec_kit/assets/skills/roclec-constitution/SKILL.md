---
name: roclec-constitution
description: Create or amend consumer project principles and their foundation references.
---

# Roclec constitution

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Inventory existing principles, constitution and source authority before editing. Preserve one canonical authority; resolve conflicting sources without overwriting them. Record project-specific principles, rationale, alternatives and provenance only within authorized scope. Link the agreed reference and its decision through references.json; an agreement cites actual source hashes. Do not treat a template or proposed principle as agreed. Analyze effects on component architecture, verification, design and existing changes. Run `foundation check --component NAME` and `check`; these validate structure/freshness, not policy quality. Keep consumer principles separate from framework behavior.
