<!-- managed by roclec-spec-kit -->
# Implementation review — TARGET / COMPONENT

## Review context

Record date, reviewer/tool, independent context, opt-in request, base and HEAD SHAs, dirty/untracked paths and exclusions. Heading language is English; prose follows project language.

## Machine-readable evidence

Use a roclec-review fenced JSON block with this shape (replace illustrative values):

```roclec-review
{
  "target": "001-feature-A1",
  "independent": true,
  "verdict": "incomplete",
  "inputs": [
    {"root": "project", "path": "specs/001-feature/spec.md", "sha256": "actual-normalized-digest"},
    {"root": "project", "path": "specs/001-feature/plan.md", "sha256": "actual-raw-digest"},
    {"root": "project", "path": "specs/001-feature/tasks.md", "sha256": "actual-normalized-digest"},
    {"root": "component:configured-component", "path": "src/changed-file.py", "sha256": "actual-raw-digest"}
  ]
}
```

Use the full directory name in target, optionally suffixed -A1. Root is project or component:<configured-name>; the explicit component: prefix also supports a component literally named project. Paths must be relative and contained within that root. Include UX for user-facing scope and all other inputs used, including code AND tests. Do not include secrets, the report itself, generated roadmap/indexes or full logs.

## Acceptance evidence

| AC reference | verified / defect / unverified / other-component | Implementation, assertions and execution | Limits |
| --- | --- | --- | --- |

## Findings

| ID | Severity | AC or rule | File and line | Condition and impact | Resolution evidence |
| --- | --- | --- | --- | --- | --- |

Explicitly state when no actionable defects were found.

## Verification and limitations

| Command or observation | Reviewer or supplied evidence | Result | Reviewed state and limits |
| --- | --- | --- | --- |

## Follow-up history

Keep dated verdicts, resolved/rejected findings with reasons, user decisions and effort when known. Give one next action and owner. ready covers only this component and these inputs.
