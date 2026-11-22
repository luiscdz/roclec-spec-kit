---
name: roclec-tasks
description: Create or revise component-owned work items and verification mapping for a native change.
---

# Roclec tasks

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Read the exact approved intent, plan, applicable ACs and component repos. Preserve existing task IDs and completed evidence. Make each task concrete with one configured owner, actual paths, dependencies and referenced AC IDs; use the consumer task format/template rather than introducing a kernel workflow language. Record real prerequisites across components. Map verification checks to applicable acceptance_ids in the profile, or identify required manual observations. Checkboxes are work notes, never evidence that a check executed or an authoritative lifecycle state. Run `check` and report blockers before implementation.

Deliver what `.roclec/flow.toml` declares in `deliverables` for stage `plan`, as support artifacts; the tasks file stays the framework's template.
