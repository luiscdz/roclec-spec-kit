<!-- managed by roclec-spec-kit -->
# Native candidate review input

Use `evidence record --file FILE` with this schema, filling values from real inspect/run records. For a change use change_id CHG-NNN and omit release. For a release use change_id null and release {component, version}. candidate_digest is the run's candidate.inputs_digest. Read policy_id from data.review_policy.id in the inspect response for the change or release. role is reviewer, or human when a person reviews. context names the session or tool that actually reviewed; it must differ from the run's producer.context (compared ignoring case and surrounding spaces) or the record is rejected as SELF_REVIEW_DECLARED. When the flow requires sessions for the review stage, context is the EVD id of the reviewer's own agent session (role reviewer, stage review, same change and component); otherwise cite it when available. For a release review this rule does not apply: context stays free text, or an EVD id of a release-stage session with role reviewer for that release. Do not fabricate independence, execution or approval.

```json
{
  "model_schema": 2,
  "kind": "independent-review",
  "change_id": null,
  "release": {"component": "configured-component", "version": "v1.0.0"},
  "component": "configured-component",
  "run_id": "RUN-001",
  "candidate_digest": "exact SHA-256 from the real run",
  "policy_id": "current policy identity from inspect",
  "actor": "declared independent reviewer",
  "role": "reviewer",
  "context": "actual tool/session identity and independence limits",
  "outcome": "incomplete",
  "acceptance_ids": [],
  "checks": [],
  "limitations": ["state what remains unverified"],
  "findings": [
    {"id": "F-1", "severity": "major", "location": {"path": "src/example.py", "line": 1},
     "acceptance_ids": [], "condition": "State when this fails", "impact": "State the observable consequence",
     "description": "Explain the issue and recommendation"}
  ],
  "resolutions": []
}
```

Ready requires sufficient checks/observations and no unresolved material defect. Use changes-needed for demonstrated defects and incomplete for missing inputs, evidence or independent context. A finding has an `F-n` ID unique within the report, severity (`blocker`, `major`, `minor`, `info`), `location` as `{path, line}` or null, applicable `acceptance_ids`, `condition`, `impact` and `description`. Its stable key is `EVD-ID#F-n`. Add `recurs_from` with a previous key when a fixed finding reappears. Each subsequent review must resolve every open or still-open finding in scope. Add an entry to `resolutions` with `finding`, `status` (`fixed` or `still-open`), the reviewed `candidate_digest` and a nonempty `note`. Only an independent reviewer or human reviewer declares these outcomes. Preserve prior reports; a new review is another EVD, never rewriting an old verdict.
