---
name: roclec-ux
description: Define AC-linked flows, states and accessibility for a user-facing Roclec feature. Use after clarification and before prototype work.
---

<!-- managed by roclec-spec-kit -->
# Roclec UX

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

Read the selected spec, product/design authority, skills-lock.json and component platform constraints. Require clarified scope and a configured user-facing component. Determine whether the feature includes a public-facing web page; if so, consult the pinned `design-taste-frontend` skill for page hierarchy and visual direction, while keeping the project's brand and design authority. The skill's page-building instructions do not apply to dashboards or app screens. Write ux.md with actors, navigation, AC-linked flows, interaction and feedback behavior, meaningful loading/empty/error/permission states, accessibility, responsive behavior and recovery. Reference acceptance criteria from spec.md rather than duplicating them. Do not create another product or design memory. Ask about unresolved user-visible choices; preserve existing decisions. Check consistency across all targeted interfaces and record intentional differences. Run `check --write`; report the result and recommend prototype, without creating it in this stage.

## Configured sources and prototype reuse

Use product/source/output/design paths from the selected component's optional product configuration; otherwise respect its existing sources. For maintenance without new interactions/states/layout, reuse approved HTML by links in prototype/references.md, relative to that file (for example ../../002-existing/prototype/index.html). The target must be in another spec's prototype directory with its original approval. Record actual approval for coverage of the current scope in this spec's prototype/review.md as well. Verify every screen/state in scope is covered; links alone do not prove it. Changes to behavior or layout require updated UX/prototype and renewed approval. Run the ready gate after recording evidence.
