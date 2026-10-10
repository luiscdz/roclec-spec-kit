---
description: "Sync a spec with Roclec project state"
---

# Roclec sync

Read `.roclec/project.toml`. For the current spec, fill `id`, `title`, `status`, `components`, `effort`, `origin` and `created` in `spec.md`; names must match configured components. Do not add a version to spec front matter. Advance `draft` to `clarified` only after open clarification markers are resolved. Run `roclec check --write` and report any errors. Do not silently invent missing acceptance criteria or release assignments.
