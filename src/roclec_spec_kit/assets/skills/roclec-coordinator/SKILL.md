---
name: roclec-coordinator
description: Start or resume Roclec changes from a natural-language request. Choose and apply the relevant native skills, continuing authorized work through component integration and pausing for decisions or missing evidence.
---

# Roclec coordinator

<!-- managed by roclec-spec-kit -->

## Determine the goal and current state

- A request to start or continue work triggers execution through integration for the requested scope. Honor narrower goals such as drafting only, reviewing, or checking status. A status request is read-only.
- Read project instructions, the profile, `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` from the installed project or linked repo, or `roclec --project ROOT --json ...`. Read `.roclec/model.md` when authoring records.
- Use `status` and `list changes` to locate relevant work. Match the request to the recorded intent and component. If the target is clear, resolve the IDs yourself. Ask which target only when more than one is plausible. Never choose by branch name or newest folder. Inspect one entity at a time with `inspect --change CHG-001`, `inspect --capability CAP-001`, `inspect --fut FUT-001`, or `inspect --release vX.Y.0 --component NAME`. For a promoted FUT, inspect the recorded decision and target before proceeding.
- On every resumption, use the current proposal digest, approvals, component progress, release membership, runs, review policy and Git state. Check any interrupted operation before repeating a write. If the goal is already satisfied, report the integration record and finish.

## Choose and execute the next skill

Load the installed skill's instructions using the host's skill mechanism or read its `SKILL.md` in `.agents/skills/` or `.claude/skills/` and follow them yourself. Resolve supporting references from that skill's directory. A separate agent is unnecessary for a skill invocation. Keep control of the workflow after each stage. Reinspect the affected scope after writes, use the applicable gate to verify prerequisites, and select the next skill in the same turn.

| Current need | Action |
| --- | --- |
| New request or a pending proposal needs revision | Use `roclec-specify` to create or revise the bundle. Reuse the existing change when the request matches it. Use `roclec-clarify` for material gaps and check the proposed intent before requesting any outstanding approval. |
| Missing foundation, design or planning | Use `roclec-foundation` to map applicable existing sources and record real agreements. Use `roclec-ux` and `roclec-prototype` when the project and change require them. Use `roclec-plan` and `roclec-tasks` to the extent the change needs, reusing existing artifacts. Apply `roclec-analyze` when consistency across artifacts needs review. |
| Missing or stale release assignment | Use `roclec-release` for planning only. Apply an agreed version and membership or a project rule that determines them. If an unpublished plan names an older digest, refresh the authorized assignment for the pending component after approval of the current digest. |
| Approved work remains to implement or verify | Check the implement gate and use `roclec-implement` on the explicit component. Reuse its recorded start if current. Run the applicable checks and obtain candidate-bound evidence. When independent review is required, use `roclec-reviewer` in a genuinely independent authorized context or arrange the review required by project policy. |
| Implementation is ready for integration | Use `roclec-converge`. Follow the project's authorized Git workflow to commit only the scoped changes and get the verified candidate into the configured target. Fetch the target tracking ref and refresh verification if the landed candidate changed. Prepare from a clean, committed code repo and apply from the configured specs trunk. Old or invalid evidence requires repair before applying. |

Work through requested components in dependency order. Preserve integrated and canceled participants and report their recorded state. Use native operations and preserve immutable history. For an integration goal, finish when inspection confirms the requested component integrations. Preparing a release for publication, creating tags, publishing and deploying require their own request.

## Continue until a decision or a real blocker

- Reuse existing authorizations. Record explicit decisions with their real actor, scope, digest and provenance as applicable. A draft, a successful gate, a budget or a FUT promotion gives no approval of intent. If intent changes, an approval for an earlier digest cannot authorize its replacement.
- Handle routine work within scope, including path discovery, JSON authoring, correcting CLI usage, running trusted checks, fixing implementation defects and recovering interrupted writes when native recovery confirms the state. Respect the configured branch boundaries, project Git policy, existing work and permissions. Avoid stashing, discarding or committing unrelated changes. Keep retrying only when the relevant precondition has changed.
- Ask only for a decision or input you cannot resolve from authoritative sources and existing authorization, such as ambiguous scope, approval of the exact proposal or prototype, an undecided release version, external evidence, or required Git acceptance. Present the concrete decision and the evidence needed, with the change ID and affected component so work can resume. Record the answer and continue as far as it authorizes, rechecking the digest and applicable gate. If a technical blocker remains after in-scope recovery, report the actual error and state without asking the user to run a routine command.
- Report the change ID, affected components, actual results and integration records. For a partial result, identify what is pending and why. Treat read-only gates as checks of recorded state. Preserve the difference between executed checks, imported observations, independent review and Git publication.
