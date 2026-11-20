# Project Constitution

**Version:** 1.0.0

## Specification before implementation

Implementation requires an unambiguous spec, reviewed UX/prototype for user-facing work, a grounded plan, component-owned tasks and one planned release assignment for each affected component.

## Sources of truth

Scope and acceptance criteria belong in spec.md. Release membership belongs in version files. Roadmap and release indexes are generated. Project rules, component architecture and contract owners remain project-owned.

## Traceable completion

Acceptance IDs and task IDs are permanent. Tasks cite [NNN/AC-NN]; tests cite the acceptance criteria they prove. Completion requires checked tasks, relevant passing tests and acceptance verification.

## Scope and decisions

Record consequential decisions and rejected alternatives. Discoveries outside active scope go to FUTURE.md. Published release files are immutable.

## Governance

Amend this constitution through roclec-constitution. Increment MAJOR for a principle removal or redefinition, MINOR for a new principle, PATCH for clarification. Review affected specs, plans and project templates. Add product, security and domain constraints from actual project evidence and user decisions.

<!-- Post-done: amendments use permanent A1 IDs, new ACs and [A1] tasks; original scope stays done. -->

## Post-completion and releases

A done spec stays done. Approved amendments have new criteria, component-owned tasks and independent release assignments. Fixes restore existing criteria. Normal releases and tags use vX.Y.0; increment X or Y and reset subordinate numbers. Only hotfixes/bugfixes increment Z, from a published tag of the same line. Record the shipped commit; never infer publication from completion.
