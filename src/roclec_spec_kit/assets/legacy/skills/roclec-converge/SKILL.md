---
name: roclec-converge
description: Verify implemented code, tasks and acceptance evidence across Roclec components before marking a feature done. Use after component implementation.
---

<!-- managed by roclec-spec-kit -->
# Roclec converge

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

1. Require in-progress status for original scope, or a selected amendment of a done spec. Read spec, plan, tasks and implementation changes in every configured component. Verify each AC against real code and relevant tests, including permissions, edge cases, UX states and integration/compatibility. Do not declare a feature done from checked boxes alone.
2. Execute relevant component test commands or report what cannot be executed. Check the AC-to-task-to-test evidence and open dependencies; record genuine gaps in the appropriate artifact without expanding scope. New discoveries go to FUTURE.
3. For an amendment verify its component tasks and ACs, retain the original spec done and run check --coverage --write; do not transition the original spec. For original scope, only after all required work and tests pass run `transition NNN done`, which rejects open tasks, missing releases and missing AC test citations. Then run `check --coverage --write`. If a repository or required verification is unavailable, retain in-progress and report the blocker.
4. Summarize verification evidence and recommend release review. Publication remains a separate explicitly authorized operation.

## Optional independent review

Read inspect reviews and the participation policy for the selected target. When explicitly enabled, obtain current ready reports for every affected component before proposing original done or amendment completion. Missing/incomplete/stale evidence goes to roclec-reviewer; demonstrated defects go to the implementer. Check semantic freshness, including newly relevant files. Never invoke yourself as an independent reviewer. User termination of the pilot is recorded with review disable and a reason, without rewriting findings. There is no new global CI gate.
