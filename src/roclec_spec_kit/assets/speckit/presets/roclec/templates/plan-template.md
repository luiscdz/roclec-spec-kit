# Implementation Plan: [FEATURE]

**Spec**: [link to spec.md] | **Date**: [YYYY-MM-DD]

## Summary

[Approach that satisfies the spec's acceptance criteria.]

## Constitution Check

[Read this project's constitution and record compliance or justified exceptions.]

## Technical Context

[Read .roclec/project.toml and each affected component's AGENTS.md and architecture docs. Use real paths and technologies; do not assume a stack.]

## Work by Component

| Component | Repository path from profile | Changes | Verification |
| --------- | ---------------------------- | ------- | ------------ |
| [name] | [path] | [files or modules] | [tests] |

## Contracts and Dependencies

[Name the owner and source of truth for any interface. Record rollout order only where needed.]

## Release Gate

After tasks and analysis, explicitly assign this spec to one planned release for every affected component. Run `roclec check --release-gate <spec>` before code changes.

## Complexity Tracking

| Exception | Why needed | Simpler alternative rejected |
| --------- | ---------- | ---------------------------- |
