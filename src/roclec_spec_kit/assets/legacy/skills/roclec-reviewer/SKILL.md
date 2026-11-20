---
name: roclec-reviewer
description: Independently review implemented behavior for a Roclec spec or amendment in one component and record acceptance evidence. Artifact analysis belongs to roclec-analyze.
---

<!-- managed by roclec-spec-kit -->
# Roclec reviewer

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

Resolve one component using configured repository paths and one explicit target (NNN or NNN-A1). Read its instructions before inspecting code. The reviewer must be a separate context that did not implement this change: an independently delegated agent when authorized or a fresh session. Without independence, prepare a handoff and mark incomplete; never relabel self-review as independent.

A user request activates participation: record `review enable TARGET --reason "user request"` unless already recorded. This policy bookkeeping is the only write allowed outside the report. Existing specs never acquire an automatic requirement. Only the user can end participation: the caller records `review disable TARGET --reason "decision"`, preserving reports and findings.

Use [references/report-template.md](references/report-template.md) to write only the component report specified by inspect. Establish explicit/PR base or discover the default branch and merge base; never assume main/master. Review committed, staged, unstaged and relevant untracked files; exclude unrelated changes without resetting them. Read actual sources rather than trusting the implementer's rationale.

Run check and the selected target's ready/release gates without --write. Trace applicable ACs through code, meaningful assertions and execution evidence. For an amendment cover its criteria and impacted regression paths. Check permissions, failure states, UX/prototype and real contracts as required by project rules. A citation is only textual traceability. Run focused checks without fix/update modes; distinguish reviewer-run evidence, supplied logs and unverified runtime/device claims. Do not edit implementation or tests.

Use ready only with sufficient execution/observation evidence and no unresolved in-scope defects; changes-needed for demonstrated defects; incomplete for missing inputs, independence or evidence. Reference AC IDs, never duplicate their authoritative text. Findings need stable IDs, file/line, failure condition and impact. Preserve dated follow-up history. Out-of-scope discoveries go to the implementer, who owns fixes and FUT entries.

Fingerprint all behavioral inputs, relevant code/tests, UX, prototypes, design and contracts, including dirty/untracked files. For spec.md and tasks.md use reviews.fingerprint(path, administrative=True), which ignores only status and task-checkbox changes. For other inputs use raw SHA-256. Record base/HEAD and independent tool/context identity. Inspect validates declared inputs and required source presence; it does not prove independence, execution or completeness of the manifest. A semantic freshness check must include newly added relevant files and excluded administrative differences. A stale report requires a new review of affected behavior.

Return one next action. Reports neither authorize publication nor change scope, tasks or status.
