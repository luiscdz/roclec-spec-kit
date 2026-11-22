# ADR-NNN: Title

Record a decision here when it affects more than one change or component, is costly to reverse, or has real alternatives with material consequences. Keep local decisions in the plan's "Decisions and alternatives".

Register this file with `reference add ADR-NNN --role decision`; its state is derived (proposed, accepted, stale, superseded) and only `foundation agree` by a real actor accepts it. Do not write a status here.

## Context and problem

What forces this decision, and what happens if nothing is decided.

## Decision drivers

- Driver that any option must satisfy or trade off.

## Considered options

Describe at least two real options, each as its own `###` subsection.

### Option 1: Name

- Advantages:
- Disadvantages:

### Option 2: Name

- Advantages:
- Disadvantages:

## Decision

The chosen option and why it wins against the drivers.

## Consequences

- Positive:
- Negative:
- Risks:

## Compliance verification

How a reviewer or check confirms that code respects this decision.

## Relations

- Supersedes: ADR IDs declared with `reference update ADR-NNN --supersedes ADR-MMM`.
- Related changes: CHG IDs that apply this decision.
