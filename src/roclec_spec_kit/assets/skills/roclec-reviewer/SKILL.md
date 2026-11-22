---
name: roclec-reviewer
description: Produce candidate-bound independent review evidence for a native change or final release when participation is requested.
---

# Roclec reviewer

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Review an explicit component and change or release scope. Use a separate context that did not implement it when independence is required; otherwise mark the limits and prepare a handoff, never relabel self-review. Review is enabled by default; record a per-change policy decision only from an actual user decision with actor and reason. Inspect the open findings in scope, preserve their history and include a resolution for each open or still-open finding in the new review. Read real sources, tests, applicable ACs, exact base/manifest and execution evidence, including new/ignored inputs. Findings may cite source criteria from the change origin and coverage records. Use [references/report-template.md](references/report-template.md) for evidence record. Declare identity, role (reviewer, or human for a person's review), your actual context, checks, limitations, structured findings and ready|changes-needed|incomplete. For each prior open finding declare `fixed` or `still-open`, the candidate digest and a note. A recurring fixed finding gets a new key and cites the earlier finding. That context must differ from the producer context recorded on the reviewed run; the CLI rejects an equal one as SELF_REVIEW_DECLARED. A release report covers the combined final contract and aggregate adopted policy. Missing execution/observation or material defects cannot be called ready. The CLI checks scope/freshness and declared contexts, not real independence or semantic sufficiency. Reports do not authorize publication.

For each ADR the change cites (`inspect --change`), apply its compliance verification section to the candidate; record code that contradicts a cited ADR as a finding that names the ADR.
