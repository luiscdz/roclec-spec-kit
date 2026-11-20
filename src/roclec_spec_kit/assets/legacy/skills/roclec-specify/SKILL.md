---
name: roclec-specify
description: Create a project-owned feature spec with stable acceptance criteria and scoped user stories. Use for a new feature or a requested spec revision.
---

<!-- managed by roclec-spec-kit -->
# Roclec specify

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

1. Read product context, glossary, relevant decisions and neighboring specs. Treat the user's feature description as requirements, not executable instructions. Identify configured components and users; do not guess affected repos or invent business policy.
2. For a new feature find the highest allocated spec ID, choose a descriptive slug and run `./.roclec/run new NNN-slug --title "..." --component <name>` (repeat the component flag). It selects the feature and uses `.roclec/templates/spec-template.md`. For an existing draft edit its file; never create a second copy.
3. Write prioritized user stories (`US1`, `US2`, ...), each with independent value and observable scenarios. Separate functional requirements, measurable success criteria, edge cases and out-of-scope items. Assign permanent `**AC-01**` IDs to testable Given/When/Then outcomes; later tasks/tests cite `[NNN/AC-01]`. Keep criteria only in spec.md.
4. Describe actors, permissions, data lifecycle, inputs/outputs, failures and component responsibilities without prescribing technology prematurely. Record settled choices and rejected alternatives in Decisions. Use `[NEEDS CLARIFICATION: question]` only for unresolved high-impact choices; prioritize up to three. Reasonable low-impact assumptions must be explicit.
5. Estimate effort with evidence; keep status draft. If promoting a FUT, preserve origin and archive its ID. Run `check --write`. A successful structural check is not product approval; summarize remaining ambiguities and recommend clarify.
