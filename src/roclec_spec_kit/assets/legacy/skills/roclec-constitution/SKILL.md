---
name: roclec-constitution
description: Create or amend project principles and synchronize impacted templates with a versioned impact report. Use when setting or changing project governance.
---

<!-- managed by roclec-spec-kit -->
# Roclec constitution

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

1. Resolve project root from config or link (no feature selection required). Read the authoritative existing constitution and project instructions. If both `.roclec/constitution.md` and `.specify/memory/constitution.md` exist with different contents, ask which to consolidate; do not maintain two sources.
2. Gather project-specific principles, constraints and amendment rules from the user/context; do not import assumptions about a product or stack. Amend the existing authority; use the seeded generic constitution for a new project. Write concrete MUST rules with rationale and observable verification. Ask about material changes rather than inventing policy.
3. Bump MAJOR for incompatible principle removal/redefinition, MINOR for new obligations, PATCH for wording. Preserve ratification date and update amendment date. Prepend a Sync Impact Report describing old/new version, changed principles, affected templates/skills/docs and pending follow-up.
4. Review `.roclec/templates/` and existing plans for conflicts; update project-owned templates and documentation as authorized. Never silently relax the kernel's release and traceability gates. If a kernel rule conflicts with intended policy, report it as a framework change. Run `check --write`; if optional spec-kit is installed, refresh its aliases with `speckit` after template changes.
