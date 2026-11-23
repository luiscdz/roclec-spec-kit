---
name: roclec-converge
description: Verify native change readiness and prepare or apply an authorized component integration.
---

# Roclec converge

<!-- managed by roclec-spec-kit -->

Read project instructions, `.roclec/project.toml` (schema 3), `.roclec/workflow.md` and applicable agreed references. Use `./.roclec/run --json ...` or `roclec --project ROOT --json ...`; the launcher supplies the project root. Select explicit CHG/CAP/FUT/release and component for mutations. Inspect with `inspect --change CHG-001`, `inspect --capability CAP-001`, or `inspect --release vX.Y.0 --component NAME`; never guess from branches or the newest folder.

Preserve consumer-owned templates, identities, decisions and immutable history. Contracts live in snapshots and current.json; release.json alone owns membership. Status is derived, never an editable done field. Read `.roclec/model.md` when authoring JSON. Passing structural checks does not establish semantic sufficiency or user approval. Complete the authorized scope; ask only for unresolved material decisions. Report actual evidence, limitations and one useful next action without executing an unauthorized action.

Inspect code, applicable ACs, meaningful assertions, current runs and observations for the explicit change/component. Before the verify gate, compare the current intent digest with its approval, release membership, run inputs and any independent report. An older participant revision, run or review is history, not current evidence; replan an authorized unpublished release before running new checks, and never redefine an already integrated participant. Run fresh checks when inputs changed; otherwise reuse only matching bytes, scope and ancestry. When independent review is enabled, current ready evidence is required by the verify/integrate gates; do not relabel self-review. Inspect the findings in scope with `list findings --change ID --open` and check that material findings have been resolved before integration. Run `check --change ID --component NAME --gate verify`. Before final integration require the whole code repo clean and committed, then `integrate prepare ID --component NAME --run RUN-ID --out FILE`; apply the concrete plan when integration is authorized. Apply revalidates; do not bypass a conflict. Operational records may dirty the repo afterward and must be committed before the next final gate. Inspect the full vector and report the preserved revision for each participant; completing one component does not complete the others or publish anything.

Where `.roclec/flow.toml` declares the `pre-integrate` hook, `integrate prepare` returns `CHECKPOINT_REQUIRED` until the person decides on the passed run's candidate: `checkpoint CHG-ID --hook pre-integrate --component NAME --run RUN-ID --digest CANDIDATE_INPUTS_DIGEST --outcome approved|rejected --actor ACTOR --reason TEXT --criteria FILE`. Present the candidate and the criteria text to the coordinator for the person; never record it yourself.
