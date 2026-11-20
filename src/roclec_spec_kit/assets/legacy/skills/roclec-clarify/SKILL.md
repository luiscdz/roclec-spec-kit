---
name: roclec-clarify
description: Resolve important ambiguities in a Roclec feature and persist decisions before planning. Use after spec authoring or when requirements conflict.
---

<!-- managed by roclec-spec-kit -->
# Roclec clarify

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

1. Inspect spec.md and map gaps across scope/actors, data and lifecycle, UX states, security/performance/accessibility, integrations and failures, edge cases, constraints, terminology and completion evidence. Mark each as clear, partial or missing; do not introduce requirements merely because a category is absent.
2. Prioritize at most five questions by impact on behavior, architecture, contracts, permissions and testability. Skip answers already present in product truth, code contracts, ADRs or prior user decisions. Ask one question at a time with concrete mutually exclusive options, consequences and a recommendation. Record the user's answer immediately, not only at the end of the interview.
3. Integrate each answer into the affected requirement or AC, remove conflicting text/markers, and append a dated decision with alternatives/reason. Preserve stable AC IDs; do not copy criteria into another document. Check new choices against other components.
4. Do not mark clarified with unanswered significant questions. When scope is settled run `./.roclec/run transition NNN clarified` then `check --write`. State unresolved items and their effect if the transition is blocked. Recommend UX for user-facing work, otherwise plan; do not start either stage here.
