# Native change bundle layout

<!-- managed by roclec-spec-kit -->

Stage a new bundle in a consumer-owned directory outside `.roclec/changes/CHG-ID`, for example `.roclec-input/CHG-ID/`. Do not construct it by moving an existing directory into one of its descendants.

The staging root contains `change.json`, the intention document cited by the record, and each complete proposed capability snapshot at the relative paths declared by the model. Read `.roclec/model.md` for the authoritative schema. Compute content hashes from the final bytes, compute `proposal_digest` last, and leave approved or integrated snapshots untouched.

Import only through the native launcher:

```text
./.roclec/run --json change new --file .roclec-input/CHG-ID/change.json
./.roclec/run --json inspect --change CHG-ID
./.roclec/run --json check --change CHG-ID --gate approve
```

The structural gate does not approve intent. Run `change approve` only when an actual actor has authorized the exact current digest. Remove staging files only after confirming the native import, and never use a rename whose destination is inside its source.
