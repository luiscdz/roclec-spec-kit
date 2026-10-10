---
description: "Implement from a configured code repository after Roclec gates"
---

# Roclec implementation handoff

Read `.roclec/project.toml` and locate the requested spec. Run `roclec check --gate <spec>` and `roclec check --release-gate <spec>`. If either fails, stop and report the errors. Implement from the configured code repository using its `roclec-implement` skill, plan and component-tagged tasks. From a sibling repo, pass `roclec --project <specs-root>` to checks. Do not mark a release published from this command.
