---
name: roclec-implement
description: Implement only the current configured component after readiness and release gates pass. Use from a code repository for a selected Roclec feature.
---

<!-- managed by roclec-spec-kit -->
# Roclec implement

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

1. Resolve the specs root using inspect and identify the current repository's configured component by its resolved path; ask if ambiguous. Read that code repo's instructions, spec, plan, tasks and relevant approved UX. Run `check --gate NNN` and `check --release-gate NNN` before code edits. Stop and report exact failures.
2. For original scope run `transition NNN in-progress` before implementation. For `NNN-A1`, keep the original spec done, use that explicit target for selection and gates, and work only on its tagged tasks. Work only on the current component's tasks in dependency order, respecting canonical contract ownership and compatibility. `[P]` is permission to reason about independence, not a requirement to spawn agents. Coordinate prerequisites through documented tasks; do not implement sibling code from the specs repo.
3. Follow project test policy and cover each acceptance criterion with meaningful tests citing `[NNN/AC-NN]`. Run relevant tests before checking a task. A citation does not prove the test passes. Update task boxes and Changed During Implementation with evidence. New scope goes to FUTURE, not silently into the active spec. Material architectural/business decisions need user input when not already settled.
4. Run `check --write`, report component completion, tests and cross-component blockers. Leave global done to converge; do not publish or close releases here.

## Optional independent review

Read inspect reviews and the participation policy for the selected target. When explicitly enabled, obtain current ready reports for every affected component before proposing original done or amendment completion. Missing/incomplete/stale evidence goes to roclec-reviewer; demonstrated defects go to the implementer. Check semantic freshness, including newly relevant files. Never invoke yourself as an independent reviewer. User termination of the pilot is recorded with review disable and a reason, without rewriting findings. There is no new global CI gate.
