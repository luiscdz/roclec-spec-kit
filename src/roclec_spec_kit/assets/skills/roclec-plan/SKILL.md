---
name: roclec-plan
description: Plan implementation and verification for an explicitly scoped native Roclec change.
---

# Roclec plan

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 2), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Inspect the proposal, exact base/proposed snapshots, foundation references, approved UX when applicable, and configured repos. Use the project-owned plan template under `.roclec/templates/`. Identify real code paths, contract ownership, dependencies, compatibility, migration/rollback and verification for each applicable AC. Separate observed facts, technical proposals and unresolved material decisions. Plans/tasks are supporting work artifacts, not a second contract or status authority. If planning changes approved behavior, update the proposal and obtain approval of that revision. Run `check` and the appropriate approve/implement gate; do not use legacy transitions or invent a ready status.
