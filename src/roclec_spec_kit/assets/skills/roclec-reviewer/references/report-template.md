<!-- managed by roclec-spec-kit -->
# Native candidate review input

Use `evidence record --file FILE` with this schema, filling values from real inspect/run records. For a change use change_id CHG-NNN and omit release. For a release use change_id null and release {component, version}. candidate_digest is the run's candidate.inputs_digest. policy_id is the adopted decision ID for a change or the aggregate ID from inspect release. Do not fabricate independence, execution or approval.

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
  "context": "actual tool/session identity and independence limits",
  "outcome": "incomplete",
  "acceptance_ids": [],
  "checks": [],
  "limitations": ["state what remains unverified"],
  "findings": []
}
```

Ready requires sufficient checks/observations and no unresolved material defect. Use changes-needed for demonstrated defects and incomplete for missing inputs, evidence or independent context. Findings contain stable id and description with file/line, failure condition, impact and AC references. Preserve prior reports; a new review is another EVD, never rewriting an old verdict.
