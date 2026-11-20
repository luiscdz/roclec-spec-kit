---
name: roclec-idea
description: Capture or retire an uncommitted project idea with a permanent FUT ID. Use for discoveries outside the active spec or backlog management.
---

<!-- managed by roclec-spec-kit -->
# Roclec idea

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

Resolve the project config/link without requiring feature selection. Read FUTURE.md and roadmap/fut-archive.md. Allocate the next FUT number above the highest live or retired ID; never reuse IDs. Record category, detected context, description, why not now, impact and proposal. Keep implementation discoveries outside active scope. When explicitly promoting/discarding an idea, retire it in the archive; a promoted spec records origin FUT-NNN. Do not create a spec unless the requested stage is specify. Run `check --write` and report the new/retired ID.
