---
description: "Plan or close a configured component release"
---

# Roclec release

Use the arguments supplied by the user. For `plan <component> <version> <spec ids...>`, run `roclec release plan <component> <version> <spec ids...>`. Each spec must target the component. For `close <component> <version>`, run `roclec check --coverage` when code repos are available, confirm publication and version-level criteria, write Release Notes in the version file, then run `roclec release close <component> <version>`. Do not edit a released file. Run `roclec check --write` after changes; release files own membership and generated views do not.
