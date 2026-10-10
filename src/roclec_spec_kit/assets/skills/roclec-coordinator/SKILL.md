---
name: roclec-coordinator
description: Inspect a Roclec project's persisted spec and release state, then recommend one next workflow step. Use when asked where a feature stands or what to do next.
---

<!-- managed by roclec-spec-kit -->
# Roclec coordinator

Read `.roclec/project.toml` and the project's `AGENTS.md` and constitution, when present. The files are the memory; do not infer progress from chat history.

Resolve the requested spec ID or `NNN-slug` without guessing. Read `specs/<name>/spec.md`, its UX, prototype, plan and tasks when present, and the version files under `roadmap/releases/<component>/`. `ROADMAP.md` and release `INDEX.md` are generated views.

Run `roclec check`, `roclec check --gate <spec>` before suggesting planning, and `roclec check --release-gate <spec>` before suggesting implementation. From a separate code repo, use its `.roclec/link.toml` if installed, or pass `roclec --project <project-root> ...`. Report real blockers and the release assignment for every component named in the spec. For a done spec, use `roclec check --coverage` when configured code repos are available.

Respond with the spec's status, evidence paths, open work or errors, and one next command with the directory in which it should run. Do not edit state in this read-only skill or invent release versions.
