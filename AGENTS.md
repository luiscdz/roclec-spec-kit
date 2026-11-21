# AGENTS.md

`roclec-spec-kit` is an installable framework for project-owned specs and releases. Keep the package independent of any consumer's product, repository names, language stack or release numbers.

## Source of truth

- `src/roclec_spec_kit/config.py`: profile schema and project discovery.
- `src/roclec_spec_kit/workflow.py`: deterministic checks and generated views.
- `src/roclec_spec_kit/cli.py`: user-facing commands.
- `src/roclec_spec_kit/native_cli.py`, `kernel.py`, `model.py`, `store.py`: profile-3 public CLI, model-schema-2 records, C1 operations and recoverable writes. `cli.legacy_main` and profile-1 helpers are regression oracles; never auto-dispatch a consumer to them.
- `src/roclec_spec_kit/authoring.py`, `causality.py`, `run_logs.py`: bundle sealing, record identity and causal ordering, and bounded local capture.
- `src/roclec_spec_kit/verification.py`, `integration.py`: candidate classification, executed runs, evidence/review gates and reconstructed integration plans.
- `src/roclec_spec_kit/releases.py`, `installation.py`: C3 final release runs, prepared Git publication records, native installation and staged adapter writes. Publication verification never pushes or creates tags.
- `src/roclec_spec_kit/viewer/`: optional read-only `roclec view` (extra `viewer`). `reader.py` projects `Kernel`, `Releases` and `Verification` without writing, executing checks or querying remotes; `docs.py` bounds the Markdown index; `server.py` is the local Flask API. `viewer-ui/` is the React/Vite source and `viewer/static/` its committed bundle: rebuild with `scripts/build_viewer.py` (CI guard: `--check`). `scripts/viewer_scenarios.py` is shared by `tests/test_viewer.py` and `harness.py --viewer`.
- `src/roclec_spec_kit/assets/`: canonical skills, templates and upstream attribution shipped in the wheel.
- `src/roclec_spec_kit/assets/legacy/`: frozen schema-1 regression assets, used only by explicit legacy oracles; never install them into native consumers.
- `src/roclec_spec_kit/assets/profiles/design-skills-lock.json`: pinned default dependencies for user-facing design work.
- `src/roclec_spec_kit/external_skills.py`: restore consumer-owned `skills-lock.json` files without guessing each repo's technology stack.
- `src/roclec_spec_kit/lifecycle.py`: worktree feature selection and guarded transitions.
- `src/roclec_spec_kit/adapter.py`: optional spec-kit aliases generated from native sources; manifests use the package version.
- `scripts/harness.py`: real-wheel lifecycle and rejection checks.
- `scripts/c1_scenarios.py`: synthetic C1 consumer scenarios, shared with unittest and the installed-wheel harness; seeded historical states do not prove integration/publication.
- `scripts/c2_scenarios.py`, `c2_faults.py`: public C2 consumer scenarios, real Git integration, competing processes and installed-wheel fault injection; reports remain synthetic observations, not independent product acceptance.
- `scripts/c3_scenarios.py`, `c3_installation.py`, `c3_faults.py`: joint release verification, real disposable Git remotes, fix/backport rejection and native Codex/Claude installation/recovery.
- `scripts/semantic_cases.json`, `semantic_scenarios.py`, `semantic_record.py`: semantic case/oracle catalog, wheel-based fixture preparation and optional future CLI telemetry. Preparation never executes agents; semantic campaigns require a separately agreed scope and budget.
- `tests/`: behavior on isolated consumer projects.

## Development roles

Subagent roles for developing this repository live in `.claude/agents/` and `.codex/agents/` (`roclec-dev-*`); they are not shipped in the wheel. Each definition is self-contained; keep both hosts in sync. Critical zones are `model.py`, `store.py`, `kernel.py`, `verification.py`, `integration.py`, `releases.py` and `installation.py` under `src/roclec_spec_kit/`: changes there use the critical implementer and a review from the other host. Agents never commit, push or decide on the user's behalf. Handoff contract, escalation, definition of done and host validation: `docs/desarrollo-con-agentes.md`. Roles that Roclec installs in consumer projects are a separate, shipped capability.

## Rules

Change generic behavior here. Consumer constitutions, specs, product design and releases belong to consumer repos. Release membership lives in version files; roadmap and indexes are generated. Never assume component names such as `api`, `web` or `mobile` in the kernel.

Before finishing a change, run `PYTHONPATH=src python3 -m unittest discover -s tests -v` and build a wheel. When changing package assets, confirm the wheel contains them and that `roclec speckit` installs into an isolated sample project. For releases, update `__version__`; the build and generated adapter use that single version.

Templates installed into consumers are project-owned and preserved by refreshes. Do not duplicate native prompts in the optional adapter. Keep the spec-kit MIT notice and source provenance when adapting upstream methods. Run the harness with `--spec-kit` for changes to lifecycle assets/adapters; this verifies Codex and Claude installation without model calls.

New releases use vX.Y.Z: normal releases increment X or Y and reset subordinate numbers (Z=0); only explicit hotfix/bugfix releases increment Z and contain fixes. Published legacy version files stay immutable. Optional product sources and review policy belong to consumers.
