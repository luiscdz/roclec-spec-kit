---
name: roclec-checklist
description: Create a tailored checklist of requirement quality for a Roclec feature. Use to review completeness and clarity before implementation.
---

<!-- managed by roclec-spec-kit -->
# Roclec checklist

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

1. Read spec, plan when present and project rules. Determine the requested focus (for example security, UX, integration or release quality). Ask only when the audience, depth or focus changes the useful result.
2. Create the first checklist via `artifact NNN checklist`; preserve existing checklists and use a descriptive additional filename for another focus. Replace generic scaffold questions with specific checks for completeness, clarity, consistency, measurability, scenarios, edge cases, dependencies and explicit assumptions.
3. Each item tests the requirements themselves: e.g. whether timeout behavior and recovery are specified with measurable thresholds. It does not instruct the reader to click a button or assert runtime behavior. Reference exact sections/ACs and label missing definitions as gaps. Keep IDs stable when revising.
4. Do not claim a checklist passes without reviewing its items, and do not automatically change status. Run `check --write` after authorized edits and recommend the stage that resolves uncovered gaps.
