---
name: roclec-coordinator
description: Inspect persisted Roclec state, blockers and release assignments and recommend one next stage. Use to resume a specific feature or ask what comes next.
---

<!-- managed by roclec-spec-kit -->
# Roclec coordinator

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

This stage is read-only. Run `inspect NNN --json` (or inspect saved selection) and `check`; read artifacts and project instructions needed to interpret the result. Report actual status, available/missing artifacts, release per component, structural errors and semantic blockers visible in the files. The CLI next_skill is a suggestion: prefer repairing a real blocker over advancing. Recommend exactly one invocation with the feature ID and explain why. Do not change selection, files or status and do not invoke the next stage. Chat history alone is not completion evidence.

## Component session context

Use inspect --component NAME when repository ownership is ambiguous. Report that component’s open tasks, applicable AC IDs, recorded dependencies, decisions/deviations and release. For done specs inspect amendments: use next_target for the explicit NNN-A1, asking which when selection_required contains multiple actionable targets. Inspect reports include optional review state; request missing/stale/incomplete reviews only when participation is enabled. For changes-needed recommend implementation. Do not infer dependencies from component names, rely on branch-name conventions or change selection.
