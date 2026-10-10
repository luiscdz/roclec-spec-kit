---
description: "Check Roclec spec-to-code convergence in configured repositories"
---

# Roclec convergence handoff

Read `.roclec/project.toml`, `spec.md`, `plan.md`, `tasks.md` and relevant component code/tests. Run `roclec check --coverage` and the code repo's own tests. Report missing acceptance coverage, unfinished tasks or contract drift. Make fixes in the affected repository; do not infer convergence from generated roadmap status alone.
