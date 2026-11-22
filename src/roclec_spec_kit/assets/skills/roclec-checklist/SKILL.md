---
name: roclec-checklist
description: Review native Roclec requirement quality and record a focused checklist for an explicit capability or change.
---

<!-- managed by roclec-spec-kit -->
# Roclec checklist

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies ROOT. Inspect the explicit CHG or CAP and select the relevant component without guessing from branches or the newest directory. Read `.roclec/model.md` when checking JSON authoring constraints.

Review the authoritative requirement/AC snapshots and proposal, plan when relevant, and consumer rules. Focus the checklist on the requested question: completeness, clarity, consistency, measurable outcomes, permissions, failure/recovery, dependencies or assumptions. Do not invent requirements merely to fill a category. Cite exact REQ/AC revisions and source paths rather than copying their text into another authority.

Use the consumer-owned checklist template/format and preserve existing IDs and reviewed evidence. Each item reviews the requirements themselves; a list of user clicks is not a requirements-quality check. Record an item as checked only after actually reviewing it. Keep unresolved material decisions visible with their impact and consult the user only when existing decisions do not settle them.

Run `check` and, for a change definition, `check --change CHG-ID --gate approve` to report deterministic results separately from semantic findings. Neither those checks nor a completed checklist approve intent, execute product tests, integrate a component or publish a release. Status is derived from native records; do not write a done field or edit generated views. Complete the authorized review and report findings, evidence, limitations and one useful next action.

Deliver the declared `deliverables` of the stage in `.roclec/flow.toml` when present. A checklist result is not a person's criteria evaluation; approvals use `--criteria FILE` through the coordinator.
