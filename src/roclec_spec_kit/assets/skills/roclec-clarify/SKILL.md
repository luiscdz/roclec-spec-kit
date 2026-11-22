---
name: roclec-clarify
description: Resolve material uncertainty in a native change proposal while preserving approved and integrated history.
---

# Roclec clarify

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Inspect the change and applicable source decisions. Turn every `coverage` gap into a question for the user and record its resolution as covered, excluded or deferred. Identify gaps affecting behavior, permissions, architecture, contracts or verification; do not invent requirements merely to fill a checklist. Ask focused questions only for material choices not already resolved. Record answers and rationale in the proposal or canonical reference, update affected obligation/AC snapshots and hashes, and preserve old approvals. A new semantic digest needs explicit approval. A pending revision may not redefine an already integrated participant; a different integrated obligation requires another change. Run the approve gate and report remaining uncertainty.

When an answer meets the ADR criterion of `roclec-specify`, record it as a proposed ADR and update `architecture_decisions` instead of burying it in the proposal. Editing an accepted ADR makes it stale and blocks implementation until the user agrees it again; to change an accepted decision, prefer a new ADR registered with `--supersedes` the old one.

Inspect rejection history and incorporate every requested correction in the revision. Link the rejection and each correction through `semantic.addresses`; mark a correction disputed only with a reason and return it to the coordinator for the user's decision.

A user's answer to a question is not the approve decision: present the revised digest to the coordinator, which asks the approve criteria (`--criteria FILE`) of the declared flow. Deliver the stage's `deliverables` from `.roclec/flow.toml` when declared.
