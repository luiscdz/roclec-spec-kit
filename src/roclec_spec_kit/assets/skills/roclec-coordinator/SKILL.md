---
name: roclec-coordinator
description: Inspect native contract/change/release state and identify the next useful action when resuming Roclec work.
---

# Roclec coordinator

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 2), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, `inspect --fut FUT-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

This stage is read-only. For promoted discovery inspect the FUT decision and target before the change. Then inspect the current proposal digest, its exact approval, the capability vector, per-component progress, release membership for that digest, unfinished runs and applicable review policy. Promotion, budget acceptance and a draft do not approve intent. A release entry for an older intent revision is not an assignment for the current one; report both revisions and route authorized replanning to `roclec-release` before implementation. Run `check` and an applicable gate only after this inspection, with explicit scope; gates do not execute tests. Identify missing approval, foundation, dependencies, release assignment, coverage or current review. Report the exact issue and supporting file/record. An integrated component can coexist with pending or canceled participants; publication is a separate record. If the target is ambiguous, ask instead of changing saved context or choosing a branch.
