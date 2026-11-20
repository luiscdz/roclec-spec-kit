---
name: roclec-amend
description: Classify a change to a done spec as fix, amendment or new spec and prepare approved amendment scope and tasks.
---

<!-- managed by roclec-spec-kit -->
# Roclec amend

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

1. Read the done spec, plan, tasks, decisions, UX and original releases. If it is not done, edit its active scope through the existing stages instead.
2. Classify the request, citing existing requirements: a fix restores promised behavior; an amendment extends behavior inside existing screens, permissions, operations and components; expanding those boundaries needs a new spec. Present the classification and obtain confirmation before writing unless the user already approved this exact scope. A fix adds no new AC: use release fix after implementation and record the regression evidence in Changed During Implementation.
3. For an amendment allocate A1, A2, etc. above the highest existing ID. Add new permanent AC IDs under Acceptance Criteria without editing or renumbering old criteria. Record the decision, alternatives and approver. Append before Decisions:

```markdown
## Amendments

### A1 — Short title (YYYY-MM-DD)

- **Components:** configured-component
- **AC:** AC-02, AC-03
- **Reason:** approved behavioral change
```

4. Append tasks above the highest T ID with exactly one owner and one amendment tag: `- [ ] T010 [configured-component] [A1] Implement and test [001/AC-02]`. Each affected component's tasks must cover every amendment AC. Add verification tasks for required environments. Update plan/dependencies when impacted. Changes to interactions, states or layout require updated UX/prototype and actual approval; do not bypass the design stage because this is an amendment.
5. Leave the spec done. Run check --write. Recommend release plan COMPONENT vX.Y.0 NNN-A1 for each affected component, then use NNN-A1 for implementation. Do not select versions or execute the next stage automatically.
