---
name: roclec-analyze
description: Review native proposal, contract, plan, task and verification consistency without modifying authorities.
---

# Roclec analyze

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

This stage is read-only. Inspect the change, integrated vector, exact snapshots, foundation decisions, plans/tasks and release membership. Run check and applicable gates. Review whether source criterion coverage is coherent with the captured text, the spec and its ACs, including exclusions, deferrals and derived ACs. Trace obligations/ACs to components, dependencies and meaningful verification; flag contradictions, missing coverage, unclear permissions and duplicated authority. Cite specific files/records and distinguish deterministic failures from semantic judgment. Passing check does not prove good requirements or correct code. Recommend the smallest repair supported by the findings, without silently broadening scope.
