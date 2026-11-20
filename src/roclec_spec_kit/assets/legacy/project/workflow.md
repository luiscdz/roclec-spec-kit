<!-- managed by roclec-spec-kit -->
# Roclec project workflow

The project files, rather than chat history, record progress. `.roclec/project.toml` defines component names and repositories. `AGENTS.md`, `CLAUDE.md` and any project constitution hold project-specific rules. `FUTURE.md` and `roadmap/fut-archive.md` track ideas; `specs/NNN-slug/spec.md` owns scope, acceptance criteria and status; `ux.md`, `prototype/`, `plan.md` and `tasks.md` hold the remaining feature work. `roadmap/releases/<component>/vX.Y.Z.md` owns release membership. `ROADMAP.md` and release `INDEX.md` are generated views.

| Stage | Agent skill | Persisted result |
| --- | --- | --- |
| Resume | `roclec-coordinator` | Read-only status and one next step |
| App foundation, when needed | `roclec-foundation` | Project-owned product and design guidance |
| Governance | `roclec-constitution` | Versioned project constitution and impact report |
| Requirement quality | `roclec-checklist` | Tailored checklist under `checklists/` |
| Idea | `roclec-idea` | `FUT-NNN` in `FUTURE.md` |
| Spec | `roclec-specify` | `spec.md` with `draft` status and stable `AC-NN` IDs |
| Clarification | `roclec-clarify` | Resolved questions; `clarified` status |
| UX, for user-facing components | `roclec-ux` | `ux.md` |
| Prototype, for user-facing components | `roclec-prototype` | HTML, audit and explicit approval in `prototype/review.md` |
| Plan | `roclec-plan` | Ready gate; `ready` status and `plan.md` |
| Tasks | `roclec-tasks` | `tasks.md` with configured component tags |
| Review | `roclec-analyze` | Read-only consistency findings |
| Release selection | `roclec-release` | `vX.Y.Z.md` per affected component |
| Implementation | `roclec-implement` in each code repo | Code, tests, task boxes and `in-progress` / `in-progress` status |
| Convergence | `roclec-converge` | Cross-component acceptance and test review |
| Publication | `roclec-release` | Release notes and closed version file |

Send one stage request at a time and inspect its result before the next stage. For a new feature, an agent can use `roclec new NNN-slug --title "..." --component <name>` through `./.roclec/run`. The ready gate is `./.roclec/run check --gate NNN`; the release gate is `./.roclec/run check --release-gate NNN`. Select specs with `./.roclec/run release plan <component> vX.Y.0 <ids...>`. Validate and regenerate with `./.roclec/run check --write`. When code repositories are available, use `./.roclec/run check --coverage` for completed specs. Close a published release with `./.roclec/run release close <component> vX.Y.Z --commit <shipped-sha>` after its specs are done and release notes are written.

The project may additionally install spec-kit commands via `roclec speckit`. Roclec's local lifecycle skills and CLI work without spec-kit. A repository with separate code components must give the agent filesystem access to the specs repository for task and status updates.

## Selection, templates and transitions

`new` and `use NNN` save the worktree selection in `.roclec/feature.json`; it is local context, not lifecycle memory and is ignored by Git. `inspect NNN --json` is read-only, returns absolute artifact paths and one suggested next skill. Explicit IDs override saved context. When spec-kit is installed, selection also writes `.specify/feature.json`; do not rely on branch guesses.

Project-owned `.roclec/templates/` seed spec, plan, tasks, checklists and constitution. Refreshing skills preserves those customizations. The existing `.specify/memory/constitution.md` remains authoritative for a project already using spec-kit; new native projects use `.roclec/constitution.md`. Keep one authority, never conflicting copies.

Use `transition NNN clarified`, then `transition NNN ready` after a complete plan, then `transition NNN in-progress` after tasks and releases, then `transition NNN done` after convergence. Unsupported transitions fail before edits. Manual status edits remain subject to `check` in CI. `artifact NNN plan|tasks|checklist` creates shared scaffolds and refuses overwrites; a scaffold is not a completed artifact.

Before implementation tasks must be nonempty, have unique TNNN IDs, exactly one configured owner, and citations covering each AC. Commented examples do not count. User-facing readiness requires nonempty UX/HTML and `**Status:** approved` in `prototype/review.md`, recorded only after actual user approval. Done requires checked tasks and test citations in every component; agents still execute actual tests. Release closure requires all real RC-NN criteria checked, notes and completed spec traceability; it records publication, not deployment.

The optional spec-kit preset/extension is generated from these same native skills and project templates. There are no automatic hooks chaining stages. `speckit.plan` and `roclec-plan` share one instruction source. Compatibility requires specify-cli >=0.13.4,<0.14.0, tested with 0.13.4.

## Post-completion, review and design

Use roclec-amend to classify post-done work. NNN-A1 selects an amendment with independent component assignments and tasks; never reopen the original spec. New normal versions and tags use vX.Y.0; only explicit hotfix/bugfix releases increment Z and ship fixes from a real published base tag. Closing records --commit and matching --tag; it does not publish or create tags.

roclec-reviewer is opt-in per target through review enable/disable --reason. Review in a separate context and preserve evidence/history. Coordinator inspect includes per-component tasks, dependencies, amendments and report freshness; use --component for shared repositories. Review participation is not a global CI gate.

User-facing components may opt into a product configuration with core/source/output/design paths. product --write generates views; check detects staleness without overwriting sources. Maintenance may reuse another spec's approved prototype through prototype/references.md, with a new scope approval in prototype/review.md. Changes to interaction or layout require new visual evidence.
