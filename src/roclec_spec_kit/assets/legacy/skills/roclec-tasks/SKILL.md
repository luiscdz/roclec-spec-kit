---
name: roclec-tasks
description: Generate dependency-ordered, component-owned tasks traced to feature acceptance criteria. Use after an approved Roclec plan.
---

<!-- managed by roclec-spec-kit -->
# Roclec tasks

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

1. Read spec, plan and optional research/model/contracts/quickstart. Resolve the exact component names and code paths; never infer paths from a generic template. Require a nonempty plan and ready status.
2. Create with `artifact NNN tasks` if absent. Organize tasks as setup, shared prerequisites, prioritized user stories, verification and rollout. Every checkbox is `- [ ] T001 [component] [US1] Action at actual/path [NNN/AC-01]`. IDs are unique and permanent. Use exactly one configured component owner or `[specs]`; `[US1]` and `[P]` are separate uppercase tags. Infrastructure tasks may omit AC citations, but every AC must be covered somewhere.
3. Make actions small enough to execute and verify without guessing. Write explicit dependencies and cross-component contract ordering. `[P]` means independent files and no unmet dependency; do not use it merely because tasks have different owners. Name meaningful test tasks based on the plan/project policy, including AC citations, rather than inventing a test framework.
4. Preserve completed tasks and IDs on regeneration; record scope changes instead of erasing history. Review coverage for every story/AC and orphan tasks. Run `check --write`. Recommend analyze; do not execute implementation or choose release versions.
