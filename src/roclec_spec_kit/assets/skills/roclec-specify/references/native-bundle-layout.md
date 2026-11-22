# Native change bundle layout

<!-- managed by roclec-spec-kit -->

Stage a new bundle in a consumer-owned directory outside `.roclec/changes/CHG-ID`, for example `.roclec-input/CHG-ID/`. Do not construct it by moving an existing directory into one of its descendants.

The staging root contains `change.json`, captured source Markdown declared by `semantic.origins`, the intention document cited by the record, and each proposed capability snapshot under `proposed/CAP-ID/draft/`. Run `change seal` to calculate the manifest hashes and snapshot revisions. Read `.roclec/model.md` for the authoritative schema.

Import only through the native launcher:

```text
./.roclec/run --json change seal .roclec-input/CHG-ID
./.roclec/run --json change new --file .roclec-input/CHG-ID/change.json
./.roclec/run --json inspect --change CHG-ID
./.roclec/run --json check --change CHG-ID --gate approve
```

The structural gate does not approve intent. Run `change approve` only when an actual actor has authorized the exact current digest. Use `change approve CHG-ID --digest DIGEST --actor ACTOR --reason TEXT --criteria FILE`, where FILE is that actor's evaluation of the approve criteria of `.roclec/flow.toml`. Remove staging files only after confirming the native import, and never use a rename whose destination is inside its source.
