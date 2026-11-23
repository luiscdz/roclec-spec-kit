---
name: roclec-specify
description: Create or revise a Roclec capability change bundle with exact bases, permanent obligations and testable acceptance.
---

# Roclec specify

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, `inspect --fut FUT-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Capture each source as Markdown inside the bundle, with only the text needed and personal data redacted before sealing. Declare `semantic.origins` and stable source criterion IDs, then map every criterion in `semantic.coverage` to ACs, an exclusion with reason, a deferred existing FUT, or a draft gap with a question. When an AC added or changed by the proposal has no source criterion, mark it as derived and explain the source gap it addresses. Present exclusions and deferrals for the user to decide. Read `.roclec/model.md` for the record shapes.

Inspect integrated contracts and existing identities before allocating CAP/REQ/AC/CHG IDs. Build change.json, proposal.md and complete proposed snapshots using `.roclec/model.md`, the consumer templates and [the native bundle layout](references/native-bundle-layout.md). Stage the bundle outside `.roclec/changes/CHG-ID`; never move a directory into its own descendant or edit the installed framework. Describe actors, permissions, observable behavior, failures, exclusions and component ownership without inventing business policy or technology. Declare null only for an absent capability/component base; otherwise cite the exact integrated revision. Use add/revise/replace/retire deltas. Preserve a REQ for the same obligation and allocate new ACs when behavior changes. Run `change seal DIR` to compute content hashes and the proposal digest; import with `change new --file FILE`, inspect the imported change, then run `check --change ID --gate approve`. Structural validity does not approve intent. Record approval only when the user has explicitly authorized that exact scope; otherwise present the concrete bundle for decision. A local authoring or command error is not a kernel or environment failure; report it truthfully and do not improvise authority.

Record an ADR only when a decision affects more than one change or component, is costly to reverse, or has real alternatives with material consequences; keep every other decision in the plan's "Decisions and alternatives". Draft a new ADR from `.roclec/templates/adr-template.md` in the `[adr]` folder and register it with `reference add ADR-NNN ... --role decision`, which leaves it proposed; never agree it. Registration is a trunk operation: when you run as a delegated role, return the draft instead and let the coordinator place and register it before sealing. Declare `semantic.architecture_decisions` in every bundle: `{"adrs": [{"id": "ADR-NNN"}]}`, whose sha256 `change seal` pins, or `{"none": "reason"}`. Approval rejects a bundle without the declaration (`ADR_UNDECLARED`) or with an outdated pin (`ADR_PIN_STALE`). Cite the replacing ADR, never a superseded one.

Inspect rejection history before revising a proposal. Apply each requested correction or mark it disputed with a reason in `semantic.addresses`, linked to the rejection decision and covering every correction ID. Seal the revision and return disputed corrections to the coordinator for the user's decision. The structural check cannot judge whether a correction is sufficient.

For a rejected proposal under revision, seal the external bundle with the same change ID and register it with `change new --file DIR/change.json`. Use the new digest for human review.

Deliver what the project's `.roclec/flow.toml` declares in `deliverables` for stage `define`, at those project-relative paths, as support artifacts; framework records and their formats stay fixed. When a person must approve (stage `approve`, `ai = false`), present the digest with the CR criteria text of that point and leave the decision to the coordinator; `change approve ID --digest DIGEST --actor ACTOR --reason TEXT --criteria FILE` takes the person's own evaluation and is never run by you.

When the flow requires session evidence for `define`, report your host and host session id to the coordinator, which records the session (rule in `roclec-coordinator`); a bundle may cite it in `semantic.sessions`.
