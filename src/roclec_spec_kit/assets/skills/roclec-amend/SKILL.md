---
name: roclec-amend
description: Classify follow-up work as evolution, fix or refactor and create a traceable native change.
---

# Roclec amend

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Inspect integrated and, when relevant, historical published contracts. A fix restores existing obligations with no normative delta; refactor preserves behavior; another behavior is evolution even when requested as a bug. Preserve permanent identities and old snapshots. Use another CHG and exact bases for new work, with revise/new ACs for changed behavior or explicit replace/retire for another obligation. Historical fixes declare baseline_release and implementation references; an arbitrary SHA or PR URL does not prove inclusion. Material classification/scope choices need a user decision only when not already authorized. Use change new/approve gates, never NNN-A1 folders or reopening a done spec.

Deliver the declared `deliverables` of stage `define` from `.roclec/flow.toml`. The new change needs its own approve decision with `--criteria FILE` from the person, through the coordinator.
