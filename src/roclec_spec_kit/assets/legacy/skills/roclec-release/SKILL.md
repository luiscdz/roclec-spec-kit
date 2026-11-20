---
name: roclec-release
description: Plan component releases and corrections or close a published release with verified evidence.
---

<!-- managed by roclec-spec-kit -->
# Roclec release

## Resolve context

Read the local `AGENTS.md`, `CLAUDE.md` and `.roclec/workflow.md`. Use `./.roclec/run`; from a linked code repo it discovers the specs project through `.roclec/link.toml`. For an existing feature run `./.roclec/run inspect <NNN-or-name> --json`; use its absolute `project` and artifact paths, rather than assuming specs are in the current repo. Explicit input wins over saved context. Without input use `inspect --json`; if no selection exists, ask which spec, never pick the newest folder. Mutating stages run `use <NNN>` to persist selection. Read `.roclec/project.toml` at the resolved project root and the existing constitution (`.specify/memory/constitution.md` if present, otherwise `.roclec/constitution.md`). Report conflicting constitutions instead of silently choosing one.

Run one requested stage per message. Preserve existing IDs, project customizations and human decisions. Status belongs in spec front matter; release membership belongs in version files. Generated roadmap/indexes are never edited. Use `transition` for lifecycle changes and `check --write` after artifact edits. Report files changed, checks, blockers and one next stage; do not run it automatically. An alias invoked through spec-kit follows this same workflow and uses Roclec's CLI, not upstream feature-creation scripts.

## Procedure

Read authoritative version files and project release policy. Do one requested operation:

- Plan: `release plan COMPONENT vX.Y.0 NNN NNN-A1`. Normal versions increase X or Y, resetting subordinate numbers; Z is always zero. Choose versions only with user/project authority. Membership belongs only in version files.
- Fix: `release fix COMPONENT vX.Y.Z NNN-or-- "description" COMMIT-or-PR`. Fixes restore existing behavior, add no new criteria, and are recorded in Changed During Implementation. For a correction release add `--kind hotfix` or `--kind bugfix` and `--base-tag vX.Y.PREVIOUS`. Only corrections can have Z > 0, and only fixes can ship there. Branch a correction from the latest published tag in that X.Y line, verify its ancestry and integrate it back according to project rules. Do not create tags or branches merely to satisfy a gate.
- Close: verify original specs done, amendment tasks complete for this component, coverage, real checked RC-NN criteria, actual publication and user-facing release notes separating new scope and fixes. Obtain the exact shipped commit; run `release close COMPONENT vX.Y.Z --commit SHA --tag vX.Y.Z`. The CLI records evidence and rejects tag collisions; it never creates or pushes tags. Creating or publishing a tag requires a separately authorized operation on that exact commit.

Never edit a published release. Historical vX.Y files remain readable and immutable. Do not migrate them just to adopt new formatting. Run check after operations and recommend one next stage.
