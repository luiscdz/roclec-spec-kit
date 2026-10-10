# AGENTS.md

`roclec-spec-kit` is an installable framework for project-owned specs and releases. Keep the package independent of any consumer's product, repository names, language stack or release numbers.

## Source of truth

- `src/roclec_spec_kit/config.py`: profile schema and project discovery.
- `src/roclec_spec_kit/workflow.py`: deterministic checks and generated views.
- `src/roclec_spec_kit/cli.py`: user-facing commands.
- `src/roclec_spec_kit/assets/`: skills and spec-kit preset/extension shipped in the wheel.
- `src/roclec_spec_kit/assets/profiles/design-skills-lock.json`: pinned default dependencies for user-facing design work.
- `src/roclec_spec_kit/external_skills.py`: restore consumer-owned `skills-lock.json` files without guessing each repo's technology stack.
- `tests/`: behavior on isolated consumer projects.

Change generic behavior here. Consumer constitutions, specs, product design and releases belong to consumer repos. Release membership lives in version files; roadmap and indexes are generated. Never assume component names such as `api`, `web` or `mobile` in the kernel.

Before finishing a change, run `PYTHONPATH=src python3 -m unittest discover -s tests -v` and build a wheel. When changing package assets, confirm the wheel contains them and that `roclec speckit` installs into an isolated sample project. Bump the package, preset and extension versions together for a release.
