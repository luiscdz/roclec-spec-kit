---
name: roclec-analyze
description: Read-only semantic consistency review across Roclec specs, plans, tasks and release context. Use after task generation or when checking readiness.
---

<!-- managed by roclec-spec-kit -->
# Roclec analyze

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

1. This stage is read-only: do not run `use`, `check --write`, edit status or fix artifacts. Run `inspect NNN --json` and `check`; load spec, plan, tasks, constitution and selected releases. Cite actual file lines when reporting findings.
2. Build an internal mapping of user stories/requirements/ACs to planned components, tasks and verification. Identify missing coverage, orphan tasks, duplicate rules, ambiguity, contradictory terminology or quantities, nonexistent paths, dependency ordering errors and unjustified complexity. Check UX/prototype alignment when applicable.
3. Compare architecture and source contracts with proposed design, and release membership with component targets. Constitution violations and contradictory acceptance behavior are CRITICAL. Missing required paths or AC coverage are HIGH; non-blocking clarity/ordering issues MEDIUM; editorial issues LOW. Distinguish CLI evidence from semantic judgement; do not claim that passing checks proves a good spec or correct code.
4. Return a compact table: ID, severity, location, finding, impact and suggested action, plus AC coverage and deterministic gate results. Recommend one repair stage for blockers or release planning when clean. Changes require a later requested stage.
