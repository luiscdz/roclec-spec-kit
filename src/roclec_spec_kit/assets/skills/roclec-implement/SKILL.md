---
name: roclec-implement
description: Implement a Roclec spec in a configured code component after its ready and release gates pass. Use from a code repository when asked to implement a specific spec.
---

<!-- managed by roclec-spec-kit -->
# Roclec implementation

Read the project's `.roclec/project.toml`, `AGENTS.md` and constitution, when present. Find the requested spec, then run `roclec check --gate <spec>` and `roclec check --release-gate <spec>` before changing code. From a separate code repo, resolve `.roclec/link.toml` or pass `roclec --project <project-root>`. Stop on a failed gate and report its exact error.

Implement only the tasks tagged for the current configured component. Read `spec.md`, `plan.md`, `tasks.md`, and any UX/prototype artifacts needed for those tasks. Follow the code repo's own instructions. Do not invent a contract or copy acceptance criteria into release files. Mark completed task boxes in the project specs and cite `[NNN/AC-NN]` in tests covering acceptance criteria. Record scope discoveries in `FUTURE.md` and material implementation deviations in the spec according to the project's policy.

Run the component's relevant tests, then `roclec check --write` and `roclec check --coverage` when the spec is done. Do not close a release merely because the code merged; publication and release notes are separate steps.
