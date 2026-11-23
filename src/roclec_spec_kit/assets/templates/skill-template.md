---
name: skill-name
description: One sentence saying when an agent should load this skill.
---

# Skill name

Copy this template to `.agents/skills/<skill-name>/SKILL.md`, where `<skill-name>` is the reference ID. Register the directory with `reference add <skill-name> --path .agents/skills/<skill-name> --role skill --component NAME` and agree it with `foundation agree --ref <skill-name>`. Its fingerprint covers every file in the directory: editing any of them makes it stale until it is agreed again. `roclec skills` copies it to `.claude/skills/`; edit only the canonical folder under `.agents/skills/`, never the copy.

## Purpose

What project knowledge this skill encapsulates and the problem it prevents.

## Applies to

- Stages: list them in the `skills` key of each stage in `.roclec/flow.toml`; a skill no stage lists applies to every stage.
- Components: the `--component` values of its reference.

## Authority

References and ADRs this skill puts into practice, cited by ID and path. Do not restate their content; when they change, this skill follows them.

- `reference-id` (`path/to/reference.md`)
- `ADR-NNN` (`docs/adr/ADR-NNN-title.md`)

## Conventions or procedure

The rules or steps an agent applies, stated so that they can be checked.

## Examples

Short examples of correct application, and of a common mistake if useful.

## Verification

How a reviewer checks that the work followed this skill. A reviewer may record a finding for each unmet point.
