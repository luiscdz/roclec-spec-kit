---
name: roclec-prototype
description: Create or update a consumer prototype that demonstrates native change acceptance and records actual visual decisions.
---

# Roclec prototype

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Read change scope, UX, design authority and applicable pinned skills. Reuse existing prototype artifacts where their approved scope truly applies; changed interactions require new evidence. Produce an inspectable artifact for the requested screens/states and review accessibility and usability. Present the actual artifact and its current SHA-256 to the user. Record an explicit decision with `checkpoint`, the real actor, reason and exact digest. For a rejection record the requested corrections and consequence, and inspect the history before revising. Link every correction through `addresses` when submitting a new decision. Declare the prototype path in `semantic.prototypes` so sealing pins its bytes and the implementation gate checks its current approval. Silence and structural checks are not visual approval. Do not declare a component verified from the prototype alone.

Present the criteria of the design checkpoint in `.roclec/flow.toml` (CR IDs and text) together with the artifact and its digest, and record the decision as `checkpoint PATH --outcome approved|rejected --digest SHA --actor ACTOR --reason TEXT --criteria FILE`, with the person's own evaluation; a rejection uses `reject prototype PATH --digest SHA --actor ACTOR --reason TEXT --criteria FILE --corrections FILE` and at least one `not-met` criterion. The consequence defaults to the point's `on_reject`. Deliver the stage `design` `deliverables` when declared.
