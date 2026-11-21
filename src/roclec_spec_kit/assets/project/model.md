<!-- managed by roclec-spec-kit -->
# Native record authoring — model_schema 2, profile 3

All JSON rejects duplicate/unknown keys, non-finite values and escaping/symlink content paths. Lists of IDs/components/references are sorted and unique. CAP/REQ/AC/CHG/FUT use at least three digits. RUN and EVD use ULIDs and explicit supersession. The CLI fills `supersedes` per run scope, per observed AC and per reviewer. Distinct change and release scopes do not share predecessors.

`change seal DIR` computes file hashes, snapshot revisions and the proposal digest. `change seal DIR --check` reports pending changes. Author new proposed snapshots under `proposed/CAP-NNN/draft/` and omit their `revision`; list extra semantic files as keys in `semantic.files`. Seal only an external bundle, then import it with `change new`.

## Change bundle

`change new --file /input/change.json` imports validated content inside that input directory. change.json contains model_schema, id, kind (`evolution|fix|refactor`), semantic and proposal_digest. Semantic contains:

- intention: Markdown path, normally proposal.md; files: {path: exact sha256} of intention/supporting semantic files.
- components: explicit configured names.
- bases: [{capability_id, component, revision}]. Revision null means expected absence; otherwise an exact immutable contract SHA. Each affected pair is explicit.
- deltas: add/retire {op, capability_id, requirement_id}; revise adds retire_acceptance_ids and add_acceptance_ids (optional editorial=true only when behavior truly stays identical); replace uses old_requirement/new_requirement.
- proposed: [{capability_id, components, revision}]; import a complete snapshot under proposed/CAP-NNN/SHA/.
- dependencies: [{component, capability_id, revision}] or [{component, release}]. Empty lists are explicit.
- references: [{id, sha256}] pinned to agreed reference bytes.

Evolution has explicit normative deltas. Same obligation retains REQ and gains a new immutable revision; changed behavior needs new ACs. Another obligation uses replace/retire. Fix/refactor has empty deltas/proposed and preserves exact bases. A historical fix adds baseline_release {component, version}. A fix may add fixes [{component, commit, requirement_ids, acceptance_ids, backport}]; commit is an immutable full Git SHA (40 or 64 lowercase hex digits) and must resolve locally at the final gate, and the requirement/AC IDs belong to that exact baseline. Backport is null or {commit}, with optional evidence_id when an exact report is already selected. Preparation checks the included commit and current release-scoped preservation observation, then freezes the resolved evidence ID; no future EVD ID must be guessed during approval. A PR URL or SHA-shaped string alone is insufficient. Capture implementation references before approving the fix; the kernel never guesses them from Git messages.

Approving freezes the imported snapshot and intention under revisions/<proposal_digest>. Editing semantic content creates another digest and requires another explicit approval. For pending participants, preserve completed component obligations; change already integrated behavior with another CHG. Supporting work notes need not become another normative source.

## Contract snapshot

contract.json contains model_schema, capability_id, requirements, acceptance, references and files. Requirements are [{id, statement, components, acceptance_ids}]; statement is a Markdown path. Acceptance entries are [{id, scenario, components}]; scenario is a Markdown path. Files is {each referenced Markdown path: sha256}; texts live only in those files. References are [{id, sha256}]. AC applicability must be a subset of its owner's component applicability. The contract revision resolves its original content forever.

## Foundation and decisions

references.json contains model_schema and references [{id, path, components, role, decision_id}]. Roles are context, principles, architecture, stack, engineering, verification, operations, design. Existing consumer files stay authoritative. Use `reference add|update` and `foundation agree` for decisions bound to source bytes. Each decision has a digest ID and a `previous` link within its entity chain. Change-start decisions have separate chains per change and component. Resolve any decision fork in the merge candidate before advancing trunk.

## Execution/evidence

The profile declares inputs/generated and optional excluded patterns per component. Checks declare id, argv list, cwd, timeout_seconds and optional acceptance_ids and env. Run checks only in repositories you trust. They execute the profile's argv. Raw output is local under `.roclec/runtime/logs/` and may contain secrets. A run manifest binds the captures by path, SHA-256, size and completeness. `run verify` requires `--role` (implementer, coordinator or human) and `--context` (the actual session or tool identity, one line); the run start and manifest record them as producer {role, context}.

Imported evidence contains model_schema, kind (manual|automated-import|independent-review), change_id, component, run_id, candidate_digest, actor, context, outcome, acceptance_ids, checks, limitations and findings. Each finding has id (F-n), severity (blocker|major|minor|info), location ({path, line} or null), acceptance_ids, condition, impact and description. Its stable key is EVD-ID#F-n; optional recurs_from cites a previously fixed finding. Each independent review has resolutions [{finding, status, candidate_digest, note}], resolving all open and still-open findings in scope with fixed or still-open. The reviewed candidate digest and a nonempty note are required. For a release use change_id=null and add release {component, version}; its RUN covers the final combined contracts. Outcome is pass|fail|incomplete for observations or ready|changes-needed|incomplete for independent review. Review adds policy_id and role (reviewer or human). A review context equal to its run's producer context, ignoring case and surrounding whitespace, is rejected as SELF_REVIEW_DECLARED; a run without producer cannot back a review, so rerun `run verify` with --role and --context. Roclec compares declared contexts, not real independence. Current scope/digest must match the actual run. Imported evidence always has executed_by_roclec=false. Files emitted by the CLI are immutable; subsequent observations create new EVDs.

A user decision is imported through `evidence record --file FILE` with model_schema, kind=finding-decision, change_id, component, actor, reason, findings (sorted unique keys), and status (accepted|invalid|deferred). For release scope use change_id=null and release {component, version}. Deferred requires an existing fut_id. Optional severity records a reclassification. Finding state is derived from immutable evidence. Review is enabled by default and the material severity defaults to major; `[review]` in the profile can set enabled and material_severity. An attributed review policy decision can override the default for a change. With review enabled, open material findings block verification and integration. Release gates list open, accepted and deferred findings for members and the release.

## Releases and plans

release.json is the sole membership authority: component/version/kind/base_tag and changes [{change_id, intent_revision}], with model_schema. Plan membership through the CLI. Final release verification covers all current integrated contracts (or the declared historical correction baseline), not superseded criteria from earlier member proposals. Ready requires actual tests/observations and current adopted review.

Prepare/apply creates immutable preparations/<SHA>.json. Record/apply checks an existing local and remote tag against the prepared commit and creates publication.json; publication freezes membership/contracts/candidate/evidence. The remote query is read-only. Metadata-only descendant commits may carry operational records without changing tested inputs; they do not change the prepared shipped commit. No command creates tags, pushes or deploys.
