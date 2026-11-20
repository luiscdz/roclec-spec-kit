---
name: roclec-plan
description: Produce an evidence-based implementation plan after Roclec readiness gates pass. Use after clarification and required approved UX/prototype work.
---

<!-- managed by roclec-spec-kit -->
# Roclec plan

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

1. Require clarified status (or a requested revision of an existing ready plan). Run `check --gate NNN`; resolve reported readiness failures before creating a plan. Read spec, UX, approved prototype, constitution and architecture/instructions of every affected code repo.
2. Create the initial scaffold with `artifact NNN plan`, using the project's shared template. For an existing plan revise in place. Investigate actual code paths, libraries and canonical contracts. Distinguish observed facts, proposed changes and unresolved questions; cite repo paths or primary sources. Ask before settling unapproved architectural, contract, permission or user-visible choices.
3. Check constitution principles before and after design. Record each meaningful technical decision, alternatives and rationale; use `research.md` only if the investigation needs a durable separate record. Identify component boundaries, contract ownership, data changes, compatibility, dependencies, migration/rollback and test strategy for each AC.
4. Add `data-model.md`, `contracts/` proposals or `quickstart.md` only when useful. Link canonical DTOs/contracts; label proposals and how they are superseded. Put justified complexity in Complexity Tracking; never silently waive a principle.
5. Resolve placeholders that affect implementation; keep user stories independently deliverable where practical. Run `transition NNN ready` only after plan completion and `check --write`. Report evidence and risks, then recommend tasks.
