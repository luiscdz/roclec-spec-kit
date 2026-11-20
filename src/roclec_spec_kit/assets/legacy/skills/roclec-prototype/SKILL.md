---
name: roclec-prototype
description: Plan, build and obtain user review of a clickable HTML prototype for a Roclec interface feature. Use after UX and before technical planning.
---

<!-- managed by roclec-spec-kit -->
# Roclec prototype

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

1. Read spec, ux.md, product/design truth and skills-lock.json. Require a user-facing component and UX artifact. Propose screens, meaningful states, interactions and AC coverage; obtain approval of that visual plan before creating HTML, unless already authorized in this session.
2. Use the project's pinned design pipeline (restore missing lock dependencies with `skills --restore`). For a public-facing web page, use `design-taste-frontend` for art direction and visual review, adapting its output to the approved visual plan and project brand. Its browser scripts are optional when their runtime or browser is unavailable; record which checks ran. For dashboards and app screens, use the other relevant pinned design skills instead. Build clickable HTML under the feature's prototype directory; cover normal, empty, loading, error and permission states where relevant. Keep product/design memory in its canonical component documents.
3. Review accessibility and usability, record evidence/findings in prototype/audit.md, and present the actual artifact to the user. Apply requested corrections. Distinguish approval of the visual plan from approval of the resulting prototype.
4. Maintain prototype/review.md with `**Status:** pending` until the user explicitly accepts the current prototype. Only then set `**Status:** approved` and record date, reviewer and the user's decision/reference; never infer approval from silence or a passing check. Changes that materially alter the approved prototype require renewed review. The CLI checks the recorded status; it does not authenticate a human decision.
5. Run `check --write` if current status allows it. Do not mark ready or start plan; recommend plan only when review is approved.

## Configured sources and prototype reuse

Use product/source/output/design paths from the selected component's optional product configuration; otherwise respect its existing sources. For maintenance without new interactions/states/layout, reuse approved HTML by links in prototype/references.md, relative to that file (for example ../../002-existing/prototype/index.html). The target must be in another spec's prototype directory with its original approval. Record actual approval for coverage of the current scope in this spec's prototype/review.md as well. Verify every screen/state in scope is covered; links alone do not prove it. Changes to behavior or layout require updated UX/prototype and renewed approval. Run the ready gate after recording evidence.
