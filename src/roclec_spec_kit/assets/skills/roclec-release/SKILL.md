---
name: roclec-release
description: Plan, verify, prepare or record component Git releases using native Roclec operations and actual publication evidence.
---

# Roclec release

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Use release.json as the only membership authority. Plan with `release plan NAME VERSION --change CHG-ID` (repeat --change); normal versions increase X or Y with subordinate resets and Z=0. Only explicit hotfix/bugfix versions increase Z, contain fixes, and cite a real published base tag. Before updating an existing unpublished plan, inspect its members and the current approved intent revisions. Replanning reconstructs membership through the CLI; it must not remove integrated members or edit release.json directly. A member whose intent changed needs the current approval, a refreshed assignment and new evidence; its old runs/reviews remain history. Do not choose a version or publish beyond existing authorization.

After member integration, execute `run verify --release VERSION --component NAME --base REF --role ROLE --context CONTEXT` over the final combined contract, declaring who runs it and the real session or tool identity. Resolve coverage and any adopted independent review policy, then commit all pending code-repo changes. Run `check --component NAME --gate release --release VERSION`; export with `release prepare NAME VERSION --run RUN-ID --out FILE` and apply the concrete plan when authorized. Fixes need locally resolvable included commits or an explicit included backport with current preservation evidence.

To record an already published Git release, use `release record NAME VERSION --preparation SHA --commit REF --tag VERSION --remote REMOTE --actor NAME --reason TEXT --out FILE`, then operation apply. The CLI checks the local/remote tag (including annotated tags) against the prepared commit; it never creates tags or pushes. A local tag or unavailable remote is not publication. Preserve frozen history, metadata-only descendant commits and component independence; deployment health is separate. If interrupted, inspect/recover the journal without overwriting divergence.

Deliver the stage `release` `deliverables` declared in `.roclec/flow.toml`. If a `handoff` hook is declared, `release prepare` and the release gate return `CHECKPOINT_REQUIRED` until the person decides on each member's integration record digest: `checkpoint CHG-ID --hook handoff --component NAME --digest INTEGRATION_DIGEST --outcome approved|rejected --actor ACTOR --reason TEXT --criteria FILE`. A handoff rejection can only defer (`--consequence defer --fut FUT-ID --corrections FILE`), which then allows removing that member from the planning release through `release plan`. Never record the checkpoint or its criteria for the person.

At `release record`, the release stage requires a session when the flow says so; record and cite it as `roclec-coordinator` describes.
