"""Profile-3 authorities, proposals, decisions and queries for C1/C2.

Verification and integration are separate services; publication belongs to C3.
"""
from __future__ import annotations

from pathlib import Path
from collections import defaultdict
import copy
import re
import subprocess

from .adr import Adrs, adr_ids, declaration, in_folder, is_adr, supersession
from .config import Profile, load_profile, validate_profile
from .model import (ModelError, checked_files, digest, encoded, fields, fingerprint, identifier,
                    identities, local_path, need, read_json, schema, sha, strings, text,
                    validate_contract, validate_delta, version_key)
from .store import Store
from .origins import captured_paths, validate_coverage

FOUNDATION_ROLES = {"context", "principles", "architecture", "stack", "engineering", "verification", "operations", "design"}
REFERENCE_ID = r"[a-z][a-z0-9-]*"


class Kernel:
    def __init__(self, profile: Profile, *, allow_pending=False):
        self.profile = profile
        # A Kernel is one command's validated snapshot (its write token is fixed).
        # Reuse validated release history within that snapshot, not across CLI calls.
        self._release_history = None
        self.store = Store(profile.root)
        self.token = self.store.token()
        need(load_profile(profile.root).data == profile.data, "BASE_CONFLICT", "Profile changed while loading", exit_code=3)
        if not allow_pending:
            self.store.healthy()

    def read(self, relative):
        record = read_json(self.store.path(relative))
        need(isinstance(record, dict), "INVALID_INPUT", "Model record must be an object", exit_code=2, path=relative)
        schema(record)
        return record

    @staticmethod
    def initialize(root: Path, profile_file: Path):
        import tomllib
        try:
            raw = profile_file.read_bytes()
            data = tomllib.loads(raw.decode("utf-8"))
        except (UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise ModelError("INVALID_INPUT", f"Invalid TOML profile: {exc}", exit_code=2) from exc
        profile = validate_profile(root, data)
        store = Store(profile.root)
        store.guard_branch("init", data)
        token = store.token()
        writes = {".roclec/project.toml": raw,
                  ".roclec/current.json": encoded({"model_schema": 2, "components": {c: {} for c in sorted(profile.components)}}),
                  ".roclec/references.json": encoded({"model_schema": 2, "references": []}),
                  ".roclec/identities.json": encoded({"model_schema": 2, "identities": {}})}
        for relative in writes:
            need(not store.path(relative).exists(), "UNMANAGED_FILE", "Initialization would overwrite an existing file", path=relative)
        ignore = store.path(".gitignore")
        ignored = ignore.read_bytes() if ignore.exists() else b""
        if b".roclec/runtime/" not in ignored.splitlines():
            writes[".gitignore"] = ignored + (b"\n" if ignored and not ignored.endswith(b"\n") else b"") + b".roclec/runtime/\n"
        receipt = store.apply("init", {"profile": data}, writes, token)
        return {"profile_schema": 3, "components": sorted(profile.components), "receipt": receipt, "increment": "C3"}

    def current(self):
        current = self.read(".roclec/current.json")
        fields(current, ("model_schema", "components"))
        need(isinstance(current["components"], dict) and current["components"].keys() == self.profile.components.keys(),
             "INVALID_REFERENCE", "Current index must declare each configured component")
        for component, capabilities in current["components"].items():
            need(isinstance(capabilities, dict), "INVALID_INPUT", "Capability index must be an object", exit_code=2)
            for cap, revision in capabilities.items():
                self.contract(cap, revision)
        return current

    def contract(self, cap, revision, *, folder=None):
        identifier(cap, "CAP")
        fingerprint(revision)
        folder = folder or self.store.path(f".roclec/contracts/{cap}/{revision}")
        record = read_json(local_path(folder, "contract.json"))
        contents = validate_contract(record, folder, self.profile.components)
        need(record["capability_id"] == cap and digest(record) == revision,
             "HASH_MISMATCH", "Contract revision does not match its descriptor", entity=cap,
             expected=revision, actual=digest(record))
        return record, contents

    def registry(self):
        record = self.read(".roclec/identities.json")
        fields(record, ("model_schema", "identities"))
        need(isinstance(record["identities"], dict), "INVALID_INPUT", "identities must be an object", exit_code=2)
        for name, entry in record["identities"].items():
            fields(entry, ("kind", "owner", "introduced_by"))
            need(entry["kind"] in {"CAP", "REQ", "AC"}, "INVALID_INPUT", "Unknown identity kind", exit_code=2)
            identifier(name, entry["kind"])
            identifier(entry["owner"], "REQ" if entry["kind"] == "AC" else "CAP")
            identifier(entry["introduced_by"], "CHG")
        return record

    def references(self):
        return self._validate_references(self.read(".roclec/references.json"))

    def _validate_references(self, record):
        fields(record, ("model_schema", "references"))
        need(isinstance(record["references"], list), "INVALID_INPUT", "references must be a list", exit_code=2)
        refs = {}
        for ref in record["references"]:
            fields(ref, ("id", "path", "components", "role", "decision_id"), ("supersedes",))
            need(ref["role"] in FOUNDATION_ROLES | {"decision"}, "INVALID_INPUT", "Unknown foundation role", exit_code=2,
                 actual=ref["role"])
            decision = ref["role"] == "decision"
            need(is_adr(ref["id"]) if decision else text(ref["id"]) and re.fullmatch(REFERENCE_ID, ref["id"]) is not None,
                 "INVALID_INPUT", "Invalid reference ID for its role", exit_code=2, actual=ref["id"],
                 remediation="Role decision requires an ADR-NNN ID; every other role a lowercase ID such as architecture.")
            need(ref["id"] not in refs, "ID_COLLISION", "Duplicate reference ID", entity=ref["id"])
            self.store.path(ref["path"])
            need(set(strings(ref["components"], nonempty=True)) <= self.profile.components.keys(),
                 "INVALID_REFERENCE", "Reference names unknown components", entity=ref["id"])
            need(ref["decision_id"] is None or (text(ref["decision_id"]) and re.fullmatch(r"[a-zA-Z0-9-]+", ref["decision_id"])),
                 "INVALID_INPUT", "Invalid foundation decision ID", exit_code=2)
            need(("supersedes" in ref) == decision, "INVALID_INPUT", "Only decision references carry supersedes",
                 exit_code=2, entity=ref["id"])
            if decision:
                adr_ids(ref["supersedes"])
            refs[ref["id"]] = ref
        supersession(refs)
        return refs

    def write_reference(self, action, ref_id, path, components, role, supersedes=()):
        refs = self.references()
        need((ref_id in refs) == (action == "update"), "INVALID_REFERENCE",
             f"Cannot {action} reference with this ID", entity=ref_id)
        need(not supersedes or role == "decision", "INVALID_INPUT", "--supersedes applies only to role decision",
             exit_code=2, entity=ref_id, remediation="Remove --supersedes, or register an ADR-NNN with --role decision.")
        ref = {"id": ref_id, "path": path, "components": sorted(components),
               "role": role, "decision_id": None}
        if role == "decision":
            ref["supersedes"] = sorted(supersedes)
        refs[ref_id] = ref
        record = {"model_schema": 2, "references": [refs[key] for key in sorted(refs)]}
        self._validate_references(record)
        folder = self.profile.adr["path"]
        need(role != "decision" or in_folder(path, folder), "INVALID_PATH",
             "An ADR must be a Markdown file inside the configured ADR folder", exit_code=2, entity=ref_id,
             expected=folder, actual=path, remediation="Place the ADR under the [adr] path of the profile (default docs/adr).")
        source = self.store.path(path)
        need(source.is_file() and bool(source.read_bytes().strip()), "INVALID_REFERENCE",
             "Reference requires an existing nonempty source", path=path)
        receipt = self.store.apply("reference-" + action, {"id": ref_id},
                                   {".roclec/references.json": encoded(record)}, self.token)
        return {"reference": ref, "receipt": receipt}

    def agree_foundation(self, ref_id, actor, reason):
        need(text(actor) and text(reason), "INVALID_INPUT", "Actor and reason are required", exit_code=2)
        refs = self.references()
        need(ref_id in refs, "INVALID_REFERENCE", "Unknown foundation reference", entity=ref_id)
        ref = refs[ref_id]
        source = self.store.path(ref["path"])
        need(source.is_file(), "FOUNDATION_INCOMPLETE", "Reference source is missing", path=ref["path"])
        content = source.read_bytes()
        need(bool(content.strip()), "FOUNDATION_INCOMPLETE", "Reference source is empty", path=ref["path"])
        extra = {"supersedes": list(ref["supersedes"])} if ref["role"] == "decision" else {}
        decision, path = self._decision("foundation", ref_id, actor, reason, status="agreed", sources={ref_id: sha(content)}, **extra)
        decision_id = decision["id"]
        ref["decision_id"] = decision_id
        writes = {".roclec/references.json": encoded({"model_schema": 2, "references": [refs[k] for k in sorted(refs)]}),
                  path: encoded(decision)}
        receipt = self.store.apply("foundation-agree", {"id": ref_id}, writes, self.token)
        return {"reference": ref, "decision": decision, "receipt": receipt}

    def foundation(self, component, change=None):
        self.profile.repo(component)
        refs = self.references()
        roles, resolved, issues = set(), [], []
        for ref in refs.values():
            # ADRs are not foundation roles: a proposed ADR never blocks unrelated changes.
            if component not in ref["components"] or ref["role"] == "decision":
                continue
            try:
                path = self.store.path(ref["path"])
                need(path.is_file() and bool(path.read_bytes().strip()), "FOUNDATION_INCOMPLETE",
                     "Reference has no content", path=ref["path"])
                need(ref["decision_id"] is not None, "FOUNDATION_INCOMPLETE", "Reference has no agreement", entity=ref["id"])
                decision = self.read(f".roclec/decisions/{ref['decision_id']}.json")
                fields(decision, ("model_schema", "id", "kind", "entity", "previous", "status", "actor", "reason", "sources"))
                need(decision["id"] == ref["decision_id"] and decision["kind"] == "foundation"
                     and decision["status"] == "agreed" and text(decision["actor"]) and text(decision["reason"]),
                     "FOUNDATION_INCOMPLETE", "Reference decision is not agreed", entity=ref["id"])
                need(isinstance(decision["sources"], dict) and decision["sources"].get(ref["id"]) == sha(path.read_bytes()),
                     "FOUNDATION_INCOMPLETE", "Reference changed since its agreement", entity=ref["id"])
                roles.add(ref["role"])
                resolved.append({**ref, "sha256": sha(path.read_bytes())})
            except ModelError as exc:
                issues.append(exc.issue)
        required = {"context", "principles", "architecture", "stack", "engineering", "verification"}
        if self.profile.components[component]["user_facing"]:
            required.add("design")
        for role in sorted(required - roles):
            issues.append(ModelError("FOUNDATION_INCOMPLETE", f"Missing agreed {role} reference", entity=component).issue)
        if not self.profile.components[component]["verification"]:
            issues.append(ModelError("FOUNDATION_INCOMPLETE", "Declare executable verification checks before implementation", entity=component).issue)
        if change:
            record, _, _ = self.change(change)
            need(component in record["semantic"]["components"], "INVALID_REFERENCE", "Component is outside change scope")
        return {"component": component, "references": resolved, "issues": issues,
                "semantic_sufficiency": "requires human evaluation"}

    def _pinned_refs(self, references, *, historical=False):
        available = {} if historical else self.references()
        for ref in references:
            fields(ref, ("id", "sha256"))
            fingerprint(ref["sha256"])
            need(text(ref["id"]), "INVALID_INPUT", "Reference ID is required", exit_code=2)
            if historical:
                continue
            need(ref["id"] in available, "INVALID_REFERENCE", "Unknown pinned reference", entity=ref["id"])
            path = self.store.path(available[ref["id"]]["path"])
            need(path.is_file() and sha(path.read_bytes()) == ref["sha256"], "INVALID_REFERENCE",
                 "Pinned reference changed or is missing", entity=ref["id"])

    def change(self, change_id, *, source=None, check_base=False, historical=False, check_component=None):
        identifier(change_id, "CHG")
        folder = source or self.store.path(f".roclec/changes/{change_id}")
        record = read_json(local_path(folder, "change.json"))
        fields(record, ("model_schema", "id", "kind", "semantic", "proposal_digest"))
        schema(record)
        need(record["id"] == change_id and record["kind"] in {"evolution", "fix", "refactor"},
             "INVALID_INPUT", "Change identity/kind mismatch", exit_code=2)
        semantic = record["semantic"]
        fields(semantic, ("intention", "files", "components", "bases", "deltas", "proposed", "dependencies", "references"),
               ("baseline_release", "fixes", "origins", "coverage", "architecture_decisions"))
        scope = strings(semantic["components"], nonempty=True)
        if "architecture_decisions" in semantic:
            cited = declaration(semantic["architecture_decisions"]).get("adrs", [])
            # Historical snapshots keep their pins; only the current proposal needs registered ADRs.
            # Pins are compared at approval and gates, never here (no retroactive invalidation).
            registered = self.references() if cited and not historical else {}
            for entry in cited if not historical else []:
                need(entry["id"] in registered and registered[entry["id"]]["role"] == "decision", "INVALID_REFERENCE",
                     "Change cites an unregistered ADR", entity=entry["id"],
                     remediation="Register the ADR with reference add ADR-NNN --role decision, or remove it from architecture_decisions.")
        need(set(scope) <= self.profile.components.keys(), "INVALID_REFERENCE", "Unknown change component")
        fingerprint(record["proposal_digest"])
        need(record["proposal_digest"] == digest({k: record[k] for k in ("id", "kind", "semantic")}),
             "HASH_MISMATCH", "Proposal digest is stale", entity=change_id)
        has_origins = "origins" in semantic or "coverage" in semantic
        if has_origins:
            need("origins" in semantic and "coverage" in semantic, "ORIGIN_REQUIRED",
                 "Declare origins and coverage together", entity=change_id,
                 remediation="Capture the origins and map their criteria to ACs")
            paths = captured_paths(semantic["origins"], entity=change_id)
            need(isinstance(semantic["files"], dict), "INVALID_INPUT", "files must be an object", exit_code=2)
            for origin, path in zip(semantic["origins"], paths):
                need(path in semantic["files"], "INVALID_ORIGIN", "Captured origin must be included in semantic.files",
                     entity=origin["id"], path=path, remediation="Add the captured Markdown to semantic.files and seal again")
                need(local_path(folder, path).is_file(), "INVALID_REFERENCE", "Captured origin file is missing",
                     entity=origin["id"], path=path, remediation="Restore the captured Markdown before sealing or approving")
        content = checked_files(folder, semantic["files"])
        need(not any(Path(p).parts[0] in {"proposed", "revisions"} for p in content),
             "INVALID_PATH", "Proposal documents cannot occupy snapshot namespaces", exit_code=2)
        need(isinstance(semantic["intention"], str) and semantic["intention"] in content,
             "INVALID_REFERENCE", "Change intention must name its Markdown content")
        for key in ("bases", "deltas", "proposed", "dependencies", "references"):
            need(isinstance(semantic[key], list), "INVALID_INPUT", f"{key} must be a list", exit_code=2)
        self._pinned_refs(semantic["references"], historical=historical)
        need([r["id"] for r in semantic["references"]] == sorted({r["id"] for r in semantic["references"]}),
             "INVALID_INPUT", "Pinned references must be sorted and unique", exit_code=2)
        current = self.current()["components"]
        bases, base_ids = {}, {}
        baseline = None
        if "baseline_release" in semantic:
            fields(semantic["baseline_release"], ("component", "version"))
            need(record["kind"] == "fix", "INVALID_REFERENCE", "Only a fix can target a historical release")
            key = semantic["baseline_release"]
            if not historical:
                baseline = self.release(key["component"], key["version"])
                need(baseline["publication"] is not None, "INVALID_REFERENCE", "Baseline release must be published")
            need(scope == [key["component"]], "INVALID_REFERENCE", "Historical fix must have one baseline component")
        for base in semantic["bases"]:
            fields(base, ("capability_id", "component", "revision"))
            cap = identifier(base["capability_id"], "CAP")
            component = base["component"]
            need(component in scope, "INVALID_REFERENCE", "Base component is outside change scope")
            pair = (cap, component)
            need(pair not in bases, "INVALID_REFERENCE", "Duplicate base pair")
            desc = None
            if base["revision"] is not None:
                desc, _ = self.contract(cap, base["revision"])
                base_ids.update(identities(desc))
            if check_base and (check_component is None or component == check_component) and not self.integration(change_id, component):
                actual = baseline["publication"]["contracts"].get(cap) if baseline else current[component].get(cap)
                need(actual == base["revision"], "BASE_CONFLICT", "Integrated revision differs from approved base",
                     exit_code=3, entity=f"{cap}/{component}", expected=base["revision"], actual=actual)
            bases[pair] = desc
        proposed, files = {}, dict(content)
        for entry in semantic["proposed"]:
            fields(entry, ("capability_id", "components", "revision"))
            cap, revision = entry["capability_id"], entry["revision"]
            need(cap not in proposed, "INVALID_REFERENCE", "Duplicate proposed capability")
            components = strings(entry["components"], nonempty=True)
            need(set(components) <= set(scope), "INVALID_REFERENCE", "Proposed capability exceeds change scope")
            relative = f"proposed/{identifier(cap, 'CAP')}/{fingerprint(revision)}"
            desc, markdown = self.contract(cap, revision, folder=local_path(folder, relative))
            need(all(set(r["components"]) <= set(components) for r in desc["requirements"]),
                 "INVALID_REFERENCE", "Proposed requirements exceed declared applicability")
            self._pinned_refs(desc["references"], historical=historical)
            proposed[cap] = (entry, desc)
            files[f"{relative}/contract.json"] = encoded(desc)
            files.update({f"{relative}/{p}": b for p, b in markdown.items()})
        delta_fields = {
            "add": ("op", "capability_id", "requirement_id"),
            "retire": ("op", "capability_id", "requirement_id"),
            "revise": ("op", "capability_id", "requirement_id", "retire_acceptance_ids", "add_acceptance_ids"),
            "replace": ("op", "capability_id", "old_requirement", "new_requirement"),
        }
        for delta in semantic["deltas"]:
            need(isinstance(delta, dict) and delta.get("op") in delta_fields, "INVALID_INPUT", "Unknown delta operation", exit_code=2)
            fields(delta, delta_fields[delta["op"]], ("editorial",) if delta["op"] == "revise" else ())
            need(delta["capability_id"] in proposed, "INVALID_REFERENCE", "Delta has no proposed contract")
            for key in ("requirement_id", "old_requirement", "new_requirement"):
                if key in delta:
                    identifier(delta[key], "REQ")
            if delta["op"] == "revise":
                need("editorial" not in delta or type(delta["editorial"]) is bool,
                     "INVALID_INPUT", "editorial must be boolean", exit_code=2)
                for key in ("retire_acceptance_ids", "add_acceptance_ids"):
                    for ac in strings(delta[key]):
                        identifier(ac, "AC")
        if record["kind"] == "evolution":
            expected_pairs = {(cap, c) for cap, (entry, _) in proposed.items() for c in entry["components"]}
            need(bool(expected_pairs) and expected_pairs == bases.keys(), "INVALID_REFERENCE", "Every proposed pair needs an explicit base")
            need(bool(semantic["deltas"]), "INVALID_REFERENCE", "Evolution requires explicit normative deltas")
            for (cap, component), base in bases.items():
                deltas = [d for d in semantic["deltas"] if d["capability_id"] == cap]
                need(base is not None or all(d["op"] == "add" for d in deltas),
                     "INVALID_REFERENCE", "An absent base only permits additions")
                validate_delta(base, proposed[cap][1], component, deltas)
            for delta in semantic["deltas"]:
                cap = delta["capability_id"]
                old_requirements = {r["id"] for (bcap, _), base in bases.items() if bcap == cap and base
                                    for r in base["requirements"]}
                new_requirements = {r["id"] for r in proposed[cap][1]["requirements"]}
                if delta["op"] == "replace":
                    need(delta["old_requirement"] in old_requirements and delta["new_requirement"] in new_requirements,
                         "INVALID_REFERENCE", "Replacement cites an unknown requirement")
                else:
                    need(delta["requirement_id"] in old_requirements | new_requirements,
                         "INVALID_REFERENCE", "Delta cites an unknown requirement")
                if delta["op"] == "revise":
                    old_acs = {a for (bcap, _), base in bases.items() if bcap == cap and base for r in base["requirements"]
                               if r["id"] == delta["requirement_id"] for a in r["acceptance_ids"]}
                    new_acs = {a for r in proposed[cap][1]["requirements"] if r["id"] == delta["requirement_id"] for a in r["acceptance_ids"]}
                    need(set(delta["retire_acceptance_ids"]) == old_acs - new_acs
                         and set(delta["add_acceptance_ids"]) == new_acs - old_acs,
                         "INVALID_REFERENCE", "AC delta must exactly match this requirement's criteria")
        else:
            need(not semantic["deltas"] and not semantic["proposed"], "INVALID_REFERENCE",
                 "Fix/refactor must preserve the normative contract")
            need(bool(bases) or bool(semantic["references"]), "INVALID_REFERENCE", "Preservation needs a contract or pinned source")
        for dep in semantic["dependencies"]:
            need(isinstance(dep, dict), "INVALID_INPUT", "Dependency must be an object", exit_code=2)
            if "release" in dep:
                fields(dep, ("component", "release"))
                version_key(dep["release"], historical=True)
            else:
                fields(dep, ("component", "capability_id", "revision"))
                identifier(dep["capability_id"], "CAP")
                fingerprint(dep["revision"])
            need(dep["component"] in self.profile.components, "INVALID_REFERENCE", "Unknown dependency component")
        if "fixes" in semantic:
            need(record["kind"] == "fix" and isinstance(semantic["fixes"], list), "INVALID_INPUT", "Implementation references belong only to fixes", exit_code=2)
            for fix in semantic["fixes"]:
                fields(fix, ("component", "commit", "requirement_ids", "acceptance_ids", "backport"))
                need(fix["component"] in scope and isinstance(fix["commit"], str) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", fix["commit"]),
                     "INVALID_REFERENCE", "Fix needs a scoped implementation reference")
                reqs = strings(fix["requirement_ids"], nonempty=True)
                acs = strings(fix["acceptance_ids"], nonempty=True)
                applicable_reqs = {r["id"]: r for (cap, c), desc in bases.items() if c == fix["component"] and desc
                                   for r in desc["requirements"] if c in r["components"]}
                need(set(reqs) <= applicable_reqs.keys() and set(acs) <= {a for req in reqs for a in applicable_reqs[req]["acceptance_ids"]},
                     "INVALID_REFERENCE", "Fix must restore obligations from its exact baseline")
                if fix["backport"] is not None:
                    fields(fix["backport"], ("commit",), ("evidence_id",))
                    need(isinstance(fix["backport"]["commit"], str) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", fix["backport"]["commit"]),
                         "INVALID_INPUT", "Backport needs an immutable Git commit SHA", exit_code=2)
                    if fix["backport"].get("evidence_id") is not None:
                        identifier(fix["backport"]["evidence_id"], "EVD")
        if has_origins:
            effective = dict(bases)
            changed_acs = set()
            for cap, (entry, desc) in proposed.items():
                for component in entry["components"]:
                    base = bases[(cap, component)]
                    before = {a["id"]: base["files"][a["scenario"]]
                              for a in base["acceptance"] if component in a["components"]} if base else {}
                    changed_acs.update(a["id"] for a in desc["acceptance"]
                                       if component in a["components"]
                                       and before.get(a["id"]) != desc["files"][a["scenario"]])
                    effective[(cap, component)] = desc
            acs = {a["id"] for (_, component), desc in effective.items() if desc
                   for a in desc["acceptance"] if component in a["components"]}
            validate_coverage(semantic["origins"], semantic["coverage"], acs, changed_acs, entity=change_id)
            if not historical:
                for origin in semantic["origins"]:
                    if origin["kind"] == "fut":
                        need(self.store.path(f".roclec/futs/{origin['id']}.json").is_file(), "INVALID_REFERENCE",
                             "FUT origin does not exist", entity=origin["id"],
                             remediation="Capture the FUT before importing the change")
                        self.inspect_fut(origin["id"])
                for row in semantic["coverage"]["criteria"]:
                    if row["status"] == "deferred":
                        need(self.store.path(f".roclec/futs/{row['fut']}.json").is_file(), "INVALID_REFERENCE",
                             "Deferred criterion cites a FUT that does not exist",
                             entity=f"{row['origin']}/{row['criterion']}", actual=row["fut"],
                             remediation="Capture the deferred work as a FUT and cite its ID")
                        self.inspect_fut(row["fut"])
        registry = self.registry()
        for name, meta in base_ids.items():
            existing = registry["identities"].get(name)
            need(existing is not None and all(existing.get(k) == v for k, v in meta.items()),
                 "INVALID_REFERENCE", "Base identity is missing or inconsistent in registry", entity=name)
        new_ids = {}
        for _, desc in proposed.values():
            for name, meta in identities(desc).items():
                existing = registry["identities"].get(name)
                if existing:
                    need(all(existing[k] == v for k, v in meta.items()) and
                         (name in base_ids or existing["introduced_by"] == change_id),
                         "ID_COLLISION", "Identity was already reserved by another definition", entity=name)
                else:
                    new_ids[name] = {**meta, "introduced_by": change_id}
        files["change.json"] = encoded(record)
        return record, files, new_ids

    def new_change(self, source_file):
        need(source_file.name == "change.json", "INVALID_INPUT", "Bundle manifest must be named change.json", exit_code=2)
        record = read_json(source_file)
        need(isinstance(record, dict), "INVALID_INPUT", "Change must be an object", exit_code=2)
        change_id = identifier(record.get("id"), "CHG")
        destination = f".roclec/changes/{change_id}"
        need(not self.store.path(destination).exists(), "ID_COLLISION", "Change ID already exists", entity=change_id)
        record, files, new_ids = self.change(change_id, source=source_file.parent, check_base=True)
        registry = self.registry()
        registry["identities"].update(new_ids)
        writes = {f"{destination}/{p}": b for p, b in files.items()}
        writes[".roclec/identities.json"] = encoded(registry)
        receipt = self.store.apply("change-new", {"id": change_id, "proposal_digest": record["proposal_digest"]}, writes, self.token)
        return {"change": record, "status": "draft", "receipt": receipt}

    @staticmethod
    def _decision_chain(record):
        return (record["entity"], record.get("component") if record["kind"] == "change-start" else None)

    def decisions(self, entity=None):
        chains = defaultdict(dict)
        directory = self.store.path(".roclec/decisions")
        records, seen = [], set()
        for path in sorted(directory.glob("*.json")) if directory.exists() else []:
            record = self.read(path.relative_to(self.profile.root).as_posix())
            fields(record, ("model_schema", "id", "kind", "entity", "previous", "actor", "reason"),
                   ("proposal_digest", "component", "components", "outcome", "target", "enabled", "status", "sources", "supersedes"))
            fingerprint(record["id"])
            need(record["id"] not in seen, "ID_COLLISION", "Duplicate decision digest", entity=record["id"])
            seen.add(record["id"])
            records.append((path, record))
        for path, record in records:
            need(record["id"] == path.stem and record["id"] == digest({k: v for k, v in record.items() if k != "id"}),
                 "HASH_MISMATCH", "Decision digest does not match its record", path=path.name)
            need(record["kind"] in {"change-approve", "change-start", "change-cancel", "fut-decide", "review-policy", "foundation"}
                 and text(record["actor"]) and text(record["reason"]), "INVALID_INPUT", "Invalid decision record", exit_code=2)
            if record["previous"] is not None:
                fingerprint(record["previous"])
            if record["kind"].startswith("change-") or record["kind"] == "review-policy":
                identifier(record["entity"], "CHG")
                fingerprint(record.get("proposal_digest"))
                if record["kind"] == "review-policy":
                    need(type(record.get("enabled")) is bool, "INVALID_INPUT", "Review policy must be boolean", exit_code=2)
                if record["kind"] == "change-start":
                    need(record.get("component") in self.profile.components, "INVALID_REFERENCE", "Unknown start component")
                if record["kind"] == "change-cancel":
                    need(set(strings(record.get("components"), nonempty=True)) <= self.profile.components.keys(),
                         "INVALID_REFERENCE", "Unknown canceled component")
            elif record["kind"] == "fut-decide":
                identifier(record["entity"], "FUT")
                need(record.get("outcome") in {"evaluating", "promoted", "discarded", "duplicate"}
                     and ((record["outcome"] in {"promoted", "duplicate"}) == text(record.get("target"))),
                     "INVALID_REFERENCE", "FUT decision has invalid outcome/target")
            else:
                ref = record["entity"]
                sources = record.get("sources")
                need(text(ref) and (is_adr(ref) or re.fullmatch(REFERENCE_ID, ref) is not None)
                     and record.get("status") == "agreed" and isinstance(sources, dict) and sources.keys() == {ref},
                     "INVALID_INPUT", "Invalid foundation agreement", exit_code=2)
                fingerprint(sources[ref])
                if is_adr(ref):
                    need("supersedes" in record, "INVALID_INPUT", "An ADR agreement must record its supersedes list",
                         exit_code=2, entity=ref, path=path.name)
                    adr_ids(record["supersedes"])
            need("supersedes" not in record or (record["kind"] == "foundation" and is_adr(record["entity"])),
                 "INVALID_INPUT", "Only an ADR agreement records supersedes", exit_code=2, path=path.name)
            chain = self._decision_chain(record)
            previous = record["previous"]
            existing = chains[chain].get(previous)
            need(existing is None, "DECISION_FORK", "Two decisions have the same predecessor in a chain",
                 entity="/".join(filter(None, chain)),
                 expected=previous, actual=sorted([existing["id"], record["id"]]) if existing else None)
            chains[chain][previous] = record
        result = []
        for chain, successors in sorted(chains.items(), key=lambda item: (item[0][0], item[0][1] or "")):
            previous, ordered = None, []
            while previous in successors:
                record = successors[previous]
                ordered.append(record)
                previous = record["id"]
            need(len(ordered) == len(successors), "INVALID_REFERENCE", "Decision chain has missing predecessors or a cycle",
                 entity="/".join(filter(None, chain)))
            if entity is None or chain[0] == entity:
                result.extend(ordered)
        return result

    def _decision(self, kind, entity, actor, reason, **extra):
        need(text(actor) and text(reason), "INVALID_INPUT", "Decision needs actor and reason", exit_code=2)
        record = {"model_schema": 2, "kind": kind, "entity": entity, "actor": actor, "reason": reason, **extra}
        chain = self._decision_chain(record)
        previous = [d["id"] for d in self.decisions(entity) if self._decision_chain(d) == chain]
        record["previous"] = previous[-1] if previous else None
        record["id"] = digest(record)
        return record, f".roclec/decisions/{record['id']}.json"

    def approval(self, change):
        approvals = [d for d in self.decisions(change["id"]) if d["kind"] == "change-approve"]
        return approvals[-1] if approvals else None

    def _origin_approval(self, record):
        semantic = record["semantic"]
        need("origins" in semantic and "coverage" in semantic, "ORIGIN_REQUIRED",
             "Approval requires captured origins and coverage", entity=record["id"],
             remediation="Add origins and coverage to the proposal and seal it again")
        for row in semantic["coverage"]["criteria"]:
            need(row["status"] != "gap", "ORIGIN_GAP", "Resolve the origin criterion before approval",
                 entity=f"{row['origin']}/{row['criterion']}",
                 remediation="Answer the question and mark the criterion covered, excluded or deferred")
        for origin in semantic["origins"]:
            if origin["kind"] != "fut":
                continue
            pointer, visited = origin["id"], set()
            while pointer.startswith("FUT-"):
                need(pointer not in visited, "INVALID_ORIGIN", "FUT origin has a duplicate cycle", entity=origin["id"])
                visited.add(pointer)
                fut = self.inspect_fut(pointer)
                need(fut["status"] in {"promoted", "duplicate"}, "INVALID_ORIGIN",
                     "FUT origin must be promoted or duplicate toward this change", entity=origin["id"],
                     remediation=f"Promote the FUT to {record['id']} or mark it as a duplicate toward that change")
                pointer = fut["decisions"][-1]["target"]
                if fut["status"] == "promoted":
                    break
            need(pointer == record["id"], "INVALID_ORIGIN", "FUT origin resolves to another target", entity=origin["id"],
                 expected=record["id"], actual=pointer, remediation="Use a FUT promoted or duplicate toward this change")

    def approve(self, change_id, proposal_digest, actor, reason):
        record, files, new_ids = self.change(change_id, check_base=True)
        self.preserve_integrated(record)
        need(not any(d["kind"] == "change-cancel" for d in self.decisions(change_id)),
             "CHANGE_CANCELED", "Canceled work requires a new change", entity=change_id)
        need(proposal_digest == record["proposal_digest"], "APPROVAL_STALE", "Approval must cite the exact proposal digest")
        self._origin_approval(record)
        Adrs(self).approvable(record)
        decision, path = self._decision("change-approve", change_id, actor, reason, proposal_digest=proposal_digest)
        writes = {path: encoded(decision)}
        if new_ids:
            registry = self.registry()
            registry["identities"].update(new_ids)
            writes[".roclec/identities.json"] = encoded(registry)
        revision_root = f".roclec/changes/{change_id}/revisions/{proposal_digest}"
        for p, data in files.items():
            destination = f"{revision_root}/{p}"
            if self.store.path(destination).exists():
                need(self.store.path(destination).read_bytes() == data, "HASH_MISMATCH", "Approved snapshot was modified", path=destination)
            else:
                writes[destination] = data
        receipt = self.store.apply("change-approve", {"id": change_id, "proposal_digest": proposal_digest,
                                   "actor": actor, "reason": reason}, writes, self.token)
        return {"decision": decision, "receipt": receipt}

    def _approved(self, change):
        approval = self.approval(change)
        need(approval is not None and approval["proposal_digest"] == change["proposal_digest"],
             "APPROVAL_STALE", "The current proposal has no matching approval", entity=change["id"])
        return approval

    def _component(self, change, component):
        need(component is not None, "AMBIGUOUS_COMPONENT", "Select a component explicitly", exit_code=2)
        need(component in change["semantic"]["components"], "INVALID_REFERENCE", "Component is outside change scope")

    def gate(self, change_id, component, stage, release=None):
        need(stage in {"approve", "implement", "verify", "integrate", "release"}, "INVALID_INPUT", "Unknown gate", exit_code=2)
        if stage == "release":
            need(component is not None and release is not None, "INVALID_INPUT", "Release gate needs component and version", exit_code=2)
            from .releases import Releases
            if change_id:
                members = self.release(component, release)["record"]["changes"]
                need(any(m["change_id"] == change_id for m in members), "RELEASE_UNASSIGNED", "Change is not in this release")
            return Releases(self).gate(component, release)
        record, _, _ = self.change(change_id, check_base=True, check_component=component)
        if stage == "approve":
            self._origin_approval(record)
            Adrs(self).approvable(record)
            return {"change": change_id, "gate": stage, "scope": "structural; semantic approval is explicit"}
        self._component(record, component)
        self._approved(record)
        cancellations = [d for d in self.decisions(change_id) if d["kind"] == "change-cancel"]
        need(not any(component in d["components"] for d in cancellations), "CHANGE_CANCELED", "Canceled work requires a new change", entity=change_id)
        foundation = self.foundation(component, change_id)
        if foundation["issues"]:
            raise ModelError("FOUNDATION_INCOMPLETE", "Resolve foundation before implementation", entity=component,
                             actual=foundation["issues"])
        if self.integration(change_id, component) is None:
            # An integrated component keeps its historical pins: no retroactive invalidation.
            Adrs(self).gate(record)
        assignments = [(r, entry) for r in self.releases() if r["record"]["component"] == component
                       for entry in r["record"]["changes"] if entry["change_id"] == change_id
                       and entry["intent_revision"] == record["proposal_digest"]]
        need(len(assignments) == 1, "RELEASE_UNASSIGNED", "Change needs exactly one release assignment for this component", entity=component)
        for dep in record["semantic"]["dependencies"]:
            if "release" in dep:
                satisfied = self.release(dep["component"], dep["release"])["publication"] is not None
            else:
                satisfied = self.current()["components"][dep["component"]].get(dep["capability_id"]) == dep["revision"]
            need(satisfied, "DEPENDENCY_PENDING", "Explicit dependency is not satisfied", actual=dep)
        if stage in {"verify", "integrate"}:
            from .verification import Verification
            return {**Verification(self).verify(change_id, component, final=stage == "integrate"), "gate": stage}
        return {"change": change_id, "component": component, "gate": stage, "release": assignments[0][0]["record"]["version"]}

    def start(self, change_id, component, actor):
        result = self.gate(change_id, component, "implement")
        record, _, _ = self.change(change_id)
        decision, path = self._decision("change-start", change_id, actor, "Implementation prerequisites satisfied",
                                        proposal_digest=record["proposal_digest"], component=component)
        receipt = self.store.apply("change-start", {"id": change_id, "component": component,
                                   "proposal_digest": record["proposal_digest"]}, {path: encoded(decision)}, self.token)
        return {**result, "status": "in-progress", "receipt": receipt}

    def cancel(self, change_id, actor, reason):
        record, _, _ = self.change(change_id)
        pending = [c for c in record["semantic"]["components"] if not self.integration(change_id, c)]
        need(bool(pending), "INVALID_REFERENCE", "Integrated work requires a reversal change")
        # Preserve the legacy seeded-reader guard as well as actual integration records.
        current = self.current()["components"]
        for proposed in record["semantic"]["proposed"]:
            need(not any(current[c].get(proposed["capability_id"]) == proposed["revision"] for c in proposed["components"] if c in pending),
                 "INVALID_REFERENCE", "An integrated revision requires a new reversal change")
        decision, path = self._decision("change-cancel", change_id, actor, reason,
                                        proposal_digest=record["proposal_digest"], components=pending)
        receipt = self.store.apply("change-cancel", {"id": change_id, "actor": actor, "reason": reason}, {path: encoded(decision)}, self.token)
        return {"decision": decision, "status": "canceled" if len(pending) == len(record["semantic"]["components"]) else "partially-integrated", "receipt": receipt}

    def inspect_change(self, change_id, *, deep=True):
        record, _, _ = self.change(change_id)
        approval = self.approval(record)
        valid = approval is not None and approval["proposal_digest"] == record["proposal_digest"]
        decisions = self.decisions(change_id)
        canceled_components = {c for d in decisions if d["kind"] == "change-cancel" for c in d["components"]}
        canceled = bool(canceled_components)
        progress = {c: "not-started" for c in record["semantic"]["components"]}
        integrated = {c: self.integration(change_id, c) for c in progress}
        for c, integration in integrated.items():
            if integration:
                progress[c] = "integrated"
        if valid:
            for d in decisions:
                if d["kind"] == "change-start" and d["proposal_digest"] == record["proposal_digest"]:
                    if not integrated[d["component"]]:
                        progress[d["component"]] = "in-progress"
            for component in progress:
                if integrated[component]:
                    progress[component] = "integrated"
                elif component in canceled_components:
                    progress[component] = "canceled"
                else:
                    from .verification import Verification
                    verifier = Verification(self)
                    for path in self.store.path(".roclec/runs").glob("RUN-*/manifest.json"):
                        run = verifier.read_run(path.parent.name)
                        if run["change_id"] == change_id and run["component"] == component and run["candidate"]["inputs"]["proposal_digest"] == record["proposal_digest"]:
                            progress[component] = "in-progress"
                    if deep:
                        try:
                            self.gate(change_id, component, "verify")
                            progress[component] = "verified"
                        except ModelError:
                            pass
        status = "canceled" if canceled else "draft" if not valid else "in-progress" if "in-progress" in progress.values() else "approved"
        if "integrated" in progress.values():
            status = "integrated" if all(p == "integrated" for p in progress.values()) else "partially-integrated"
        elif progress and all(p == "verified" for p in progress.values()):
            status = "verified"
        issues = []
        try:
            self.change(change_id, check_base=True)
        except ModelError as exc:
            issues.append(exc.issue)
        return {"change": record, "status": status, "components": progress, "approval": approval,
                "approval_current": valid, "decisions": decisions, "issues": issues,
                "origins": record["semantic"].get("origins", []),
                "coverage": record["semantic"].get("coverage", {"criteria": [], "derived": []}),
                "integrations": {c: r for c, r in integrated.items() if r},
                "architecture_decisions": Adrs(self).declared(record)}

    def list_records(self, category, *, origin=None):
        need(origin is None or (category == "changes" and text(origin)), "INVALID_INPUT",
             "Origin filtering requires a change list and an origin ID", exit_code=2)
        if category == "releases":
            return [{"component": item["record"]["component"], "version": item["record"]["version"],
                     "status": item["status"]} for item in self.releases()]
        if category == "changes":
            items = (self.inspect_change(path.parent.name)
                     for path in sorted(self.store.path(".roclec/changes").glob("*/change.json")))
            return [{"id": item["change"]["id"], "status": item["status"], "components": item["components"],
                     "approval_current": item["approval_current"]}
                    for item in items if origin is None or any(o["id"] == origin for o in item["origins"])]
        if category == "adrs":
            return Adrs(self).list()
        if category == "futs":
            return [{"id": path.stem, "status": self.inspect_fut(path.stem)["status"]}
                    for path in sorted(self.store.path(".roclec/futs").glob("*.json"))]
        from .verification import Verification
        verifier = Verification(self)
        result = []
        for path in sorted(self.store.path(".roclec/runs").glob("RUN-*/start.json")):
            run_id = path.parent.name
            relative = path.relative_to(self.profile.root).as_posix()
            completed = self.store.path(f".roclec/runs/{run_id}/manifest.json").is_file()
            run = verifier.read_run(run_id) if completed else self.read(relative)
            result.append({"id": run_id, "component": run["component"], "change_id": run["change_id"],
                           "release": run.get("release"), "status": run["status"] if completed else "unfinished"})
        return result

    def status(self):
        adrs = Adrs(self)
        view = adrs.view()
        components = {name: {"changes": [], "pending_gates": [], "unfinished_runs": [], "planning_releases": [],
                             "pending_adrs": adrs.pending(name, view)}
                      for name in sorted(self.profile.components)}
        gates = {"not-started": "implement", "in-progress": "verify", "verified": "integrate"}
        for change in self.list_records("changes"):
            for component, progress in change["components"].items():
                summary = components[component]
                status = progress if progress != "not-started" else "approved" if change["approval_current"] else "draft"
                summary["changes"].append({"id": change["id"], "status": status})
                gate = "approve" if status == "draft" else gates.get(progress)
                if gate:
                    summary["pending_gates"].append({"id": change["id"], "gate": gate})
        for run in self.list_records("runs"):
            if run["status"] == "unfinished":
                components[run["component"]]["unfinished_runs"].append(run["id"])
        for release in self.list_records("releases"):
            if release["status"] == "planning":
                components[release["component"]]["planning_releases"].append(release["version"])
        return {"project": self.profile.data["name"], "components": components}

    def _fut_record(self, record):
        fields(record, ("model_schema", "id", "source", "finding", "impact", "questions"))
        schema(record)
        identifier(record["id"], "FUT")
        fields(record["source"], ("location", "locator"))
        need(all(text(record[k]) for k in ("finding", "impact")) and all(text(v) for v in record["source"].values())
             and isinstance(record["questions"], list) and all(text(v) for v in record["questions"]),
             "INVALID_INPUT", "Discovery needs source, finding, impact and question strings", exit_code=2)
        return record

    def capture(self, source_file):
        record = self._fut_record(read_json(source_file))
        fut_id = record["id"]
        destination = f".roclec/futs/{fut_id}.json"
        need(not self.store.path(destination).exists(), "ID_COLLISION", "FUT ID already exists", entity=fut_id)
        receipt = self.store.apply("fut-capture", {"id": fut_id, "record": record}, {destination: encoded(record)}, self.token)
        return {"fut": record, "status": "captured", "receipt": receipt}

    def inspect_fut(self, fut_id):
        identifier(fut_id, "FUT")
        record = self._fut_record(self.read(f".roclec/futs/{fut_id}.json"))
        need(record.get("id") == fut_id, "INVALID_REFERENCE", "FUT identity mismatch")
        decisions = [d for d in self.decisions(fut_id) if d["kind"] == "fut-decide"]
        return {"fut": record, "status": decisions[-1]["outcome"] if decisions else "captured", "decisions": decisions}

    def decide_fut(self, fut_id, outcome, actor, reason, target=None):
        current = self.inspect_fut(fut_id)
        need(outcome in {"evaluating", "promoted", "discarded", "duplicate"}, "INVALID_INPUT", "Unknown FUT outcome", exit_code=2)
        need((outcome in {"promoted", "duplicate"}) == (target is not None), "INVALID_REFERENCE",
             "Only promoted/duplicate require a target")
        if outcome == "duplicate" and target.startswith("CHG-"):
            self.change(target)
        elif outcome == "duplicate":
            identifier(target, "FUT")
            visited = {fut_id}
            pointer = target
            while pointer:
                need(pointer not in visited, "INVALID_REFERENCE", "FUT duplicate cycle", entity=pointer)
                visited.add(pointer)
                other = self.inspect_fut(pointer)
                pointer = other["decisions"][-1]["target"] if other["status"] == "duplicate" else None
                if pointer and pointer.startswith("CHG-"):
                    self.change(pointer)
                    pointer = None
        elif outcome == "promoted":
            if target.startswith("CHG-"):
                self.change(target)
            elif target.startswith(("CAP-", "REQ-")):
                need(target in self.registry()["identities"], "INVALID_REFERENCE", "Promotion target does not exist", entity=target)
            else:
                need(re.fullmatch(r"[a-zA-Z0-9-]+", target) is not None, "INVALID_INPUT", "Invalid target", exit_code=2)
                decision = self.read(f".roclec/decisions/{target}.json")
                need(decision.get("kind") == "foundation", "INVALID_REFERENCE", "Target must be a foundation decision")
        need(current["status"] in {"captured", "evaluating"} or outcome == "evaluating", "INVALID_REFERENCE",
             "Reopen a resolved FUT with an explicit evaluating decision")
        decision, path = self._decision("fut-decide", fut_id, actor, reason, outcome=outcome, target=target)
        receipt = self.store.apply("fut-decide", {"id": fut_id, "outcome": outcome, "target": target,
                                   "actor": actor, "reason": reason}, {path: encoded(decision)}, self.token)
        return {"decision": decision, "status": outcome, "receipt": receipt}

    def releases(self):
        if self._release_history is not None:
            return copy.deepcopy(self._release_history)
        result, keys = [], set()
        directory = self.store.path(".roclec/releases")
        for path in sorted(directory.glob("*/*/release.json")) if directory.exists() else []:
            record = self.read(path.relative_to(self.profile.root).as_posix())
            fields(record, ("model_schema", "component", "version", "kind", "changes", "base_tag"))
            component, version = record["component"], record["version"]
            need(component in self.profile.components and path.parent.name == version and path.parent.parent.name == component,
                 "INVALID_REFERENCE", "Release identity does not match its location")
            numeric = version_key(version, historical=True)
            key = (component, numeric)
            need(key not in keys, "VERSION_INVALID", "Ambiguous normalized release version", entity=component, actual=version)
            keys.add(key)
            need(record["kind"] in {"release", "hotfix", "bugfix"} and isinstance(record["changes"], list),
                 "INVALID_INPUT", "Invalid release kind or membership", exit_code=2)
            seen = set()
            for member in record["changes"]:
                fields(member, ("change_id", "intent_revision"))
                identifier(member["change_id"], "CHG")
                fingerprint(member["intent_revision"])
                need(member["change_id"] not in seen, "INVALID_REFERENCE", "Duplicate release member")
                seen.add(member["change_id"])
            publication_path = path.parent / "publication.json"
            publication = None
            if publication_path.exists():
                publication = self.read(publication_path.relative_to(self.profile.root).as_posix())
                fields(publication, ("model_schema", "component", "version", "release_digest", "contracts", "commit", "tag", "remote", "evidence"))
                need(publication["component"] == component and publication["version"] == version
                     and publication["release_digest"] == digest(record), "HASH_MISMATCH", "Published membership was modified")
                need(isinstance(publication["contracts"], dict) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", str(publication["commit"]))
                     and publication["tag"] == version and text(publication["remote"]) and bool(publication["evidence"]),
                     "INVALID_REFERENCE", "Incomplete publication record")
                for cap, revision in publication["contracts"].items():
                    self.contract(cap, revision)
                if "preparation" in publication["evidence"]:
                    from .releases import Releases
                    prepared = Releases(self).preparation(component, version, publication["evidence"]["preparation"])
                    need(prepared["release_digest"] == publication["release_digest"] and prepared["contracts"] == publication["contracts"]
                         and prepared["candidate"]["head"] == publication["commit"] and prepared["run_id"] == publication["evidence"].get("run_id"),
                         "HASH_MISMATCH", "Publication differs from its frozen preparation")
                    query = publication["evidence"].get("query", {})
                    need(query.get("commit") == publication["commit"] and query.get("tag") == publication["tag"]
                         and query.get("remote") == publication["remote"], "INVALID_REFERENCE", "Publication lacks matching remote-query provenance")
            else:
                version_key(version)  # Legacy forms are immutable published history only.
            need((record["kind"] == "release" and numeric[2] == 0 and record["base_tag"] is None)
                 or (record["kind"] in {"hotfix", "bugfix"} and numeric[2] > 0 and text(record["base_tag"])),
                 "VERSION_INVALID", "Release kind/version/base-tag are inconsistent")
            result.append({"record": record, "publication": publication, "status": "published" if publication else "planning"})
        for release in result:
            for member in release["record"]["changes"]:
                folder = self.store.path(f".roclec/changes/{member['change_id']}/revisions/{member['intent_revision']}")
                change, _, _ = self.change(member["change_id"], source=folder, historical=True)
                need(change["proposal_digest"] == member["intent_revision"], "HASH_MISMATCH", "Approved release member was modified")
                need(any(d["kind"] == "change-approve" and d["proposal_digest"] == member["intent_revision"]
                         for d in self.decisions(member["change_id"])), "INVALID_REFERENCE", "Release member was not approved")
                need(release["record"]["component"] in change["semantic"]["components"],
                     "INVALID_REFERENCE", "Release member is outside component scope")
                need(release["record"]["kind"] == "release" or change["kind"] == "fix",
                     "VERSION_INVALID", "Correction release contains non-fix work")
        self._release_history = copy.deepcopy(result)
        return result

    def release(self, component, version):
        self.profile.repo(component)
        key = version_key(version, historical=True)
        found = [r for r in self.releases() if r["record"]["component"] == component
                 and version_key(r["record"]["version"], historical=True) == key]
        need(len(found) == 1, "INVALID_REFERENCE", "Release is missing or ambiguous", entity=f"{component}/{version}")
        return found[0]

    def release_plan(self, component, version, kind, changes, base_tag=None):
        repo = self.profile.repo(component)
        proposed = version_key(version)
        need(kind in {"release", "hotfix", "bugfix"}, "VERSION_INVALID", "Unknown release kind")
        need(len(changes) == len(set(changes)), "INVALID_REFERENCE", "Duplicate change arguments")
        releases = self.releases()
        same = [r for r in releases if r["record"]["component"] == component
                and version_key(r["record"]["version"], historical=True) == proposed]
        need(not same or (same[0]["record"]["version"] == version and same[0]["publication"] is None),
             "VERSION_INVALID", "Published or legacy equivalent version cannot be overwritten")
        published = [r for r in releases if r["record"]["component"] == component and r["publication"] is not None]
        members = []
        for change_id in sorted(changes):
            change, _, _ = self.change(change_id, check_base=True)
            self._component(change, component)
            self._approved(change)
            need(not any(d["kind"] == "change-cancel" for d in self.decisions(change_id)), "CHANGE_CANCELED", "Cannot assign canceled work")
            if kind != "release":
                need(change["kind"] == "fix", "VERSION_INVALID", "Hotfix/bugfix may contain only fixes")
            member = {"change_id": change_id, "intent_revision": change["proposal_digest"]}
            for other in releases:
                if other["record"]["component"] == component and other["record"]["version"] != version:
                    need(member not in other["record"]["changes"], "RELEASE_DUPLICATE", "Change revision is already assigned to another release")
            members.append(member)
        if kind == "release":
            need(proposed[2] == 0 and base_tag is None, "VERSION_INVALID", "Normal releases require Z=0 and no base-tag")
            if published:
                previous = max(version_key(r["record"]["version"], historical=True) for r in published)
                need((proposed[0] > previous[0] and proposed[1:] == (0, 0))
                     or (proposed[0] == previous[0] and proposed[1] > previous[1] and proposed[2] == 0),
                     "VERSION_INVALID", "Normal release must increment X/reset Y,Z or increment Y/reset Z")
        else:
            need(proposed[2] > 0 and text(base_tag), "VERSION_INVALID", "Correction needs Z>0 and a published base-tag")
            base = self.release(component, base_tag)
            need(base["publication"] is not None and version_key(base_tag, historical=True)[:2] == proposed[:2],
                 "VERSION_INVALID", "Base-tag must be published in the same X.Y line")
            line = [version_key(r["record"]["version"], historical=True)[2] for r in published
                    if version_key(r["record"]["version"], historical=True)[:2] == proposed[:2]]
            need(proposed[2] > max(line), "VERSION_INVALID", "Correction must advance beyond latest published patch")
            commit = subprocess.run(["git", "rev-parse", "--verify", f"refs/tags/{base_tag}^{{commit}}"],
                                    cwd=repo, capture_output=True, text=True, timeout=15)
            need(commit.returncode == 0 and commit.stdout.strip() == base["publication"]["commit"],
                 "INVALID_REFERENCE", "Base tag does not resolve to the recorded published commit")
        record = {"model_schema": 2, "component": component, "version": version, "kind": kind,
                  "changes": members, "base_tag": base_tag}
        if same:
            removed = [m for m in same[0]["record"]["changes"] if m not in members]
            for member in removed:
                decisions = self.decisions(member["change_id"])
                need(self.integration(member["change_id"], component) is None,
                     "CHANGE_IN_PROGRESS", "An integrated release member cannot be removed")
                started = any(d["kind"] == "change-start" and d["component"] == component
                              and d["proposal_digest"] == member["intent_revision"] for d in decisions)
                from .verification import Verification
                started = started or any(r["change_id"] == member["change_id"] and r["component"] == component
                                         for r in (Verification(self).read_run(p.parent.name) for p in self.store.path(".roclec/runs").glob("RUN-*/manifest.json")))
                canceled = any(d["kind"] == "change-cancel" and component in d["components"] for d in decisions)
                replacement = any(m["change_id"] == member["change_id"] for m in members)
                need(not started or canceled or replacement, "CHANGE_IN_PROGRESS",
                     "Cancel pending work before removing assignment, or bind its newly approved revision explicitly")
        receipt = self.store.apply("release-plan", {"component": component, "version": version, "record": record},
                                   {f".roclec/releases/{component}/{version}/release.json": encoded(record)}, self.token)
        return {"release": record, "status": "planning", "receipt": receipt}

    def inspect_capability(self, cap, component=None, at=None):
        identifier(cap, "CAP")
        need(at is None or component is not None, "AMBIGUOUS_COMPONENT", "Historical release lookup requires a component", exit_code=2)
        if component is not None:
            self.profile.repo(component)
        if at:
            release = self.release(component, at)
            need(release["publication"] is not None, "INVALID_REFERENCE", "Historical contract requires a published release")
            revision = release["publication"]["contracts"].get(cap)
            need(revision is not None, "INVALID_REFERENCE", "Release does not contain this capability")
            selected = {component: {cap: revision}}
        else:
            selected = self.current()["components"]
        vector = {}
        for name, capabilities in selected.items():
            if component and name != component:
                continue
            revision = capabilities.get(cap)
            if revision:
                contract, contents = self.contract(cap, revision)
                reqs = [r for r in contract["requirements"] if name in r["components"]]
                ac_ids = {a for r in reqs for a in r["acceptance_ids"]}
                vector[name] = {"revision": revision, "requirements": reqs,
                                "acceptance": [a for a in contract["acceptance"] if a["id"] in ac_ids and name in a["components"]],
                                "content": {p: b.decode("utf-8") for p, b in contents.items()}}
        need(bool(vector), "INVALID_REFERENCE", "Capability is not integrated in the selected scope", entity=cap)
        return {"capability_id": cap, "components": vector, "at": at}

    def check(self):
        current = self.current()
        registry = self.registry()["identities"]
        for path in self.store.path(".roclec/contracts").glob("*/*/contract.json"):
            desc, _ = self.contract(path.parent.parent.name, path.parent.name)
            for name, metadata in identities(desc).items():
                need(name in registry and all(registry[name][k] == v for k, v in metadata.items()),
                     "ID_COLLISION", "Historical contract identity conflicts with the registry", entity=name)
        self.references()
        self.decisions()
        adr_warnings = Adrs(self).structure()
        for path in self.store.path(".roclec/futs").glob("*.json"):
            self.inspect_fut(path.stem)
        for path in sorted(self.store.path(".roclec/changes").glob("*/change.json")):
            self.change(path.parent.name)
        releases = self.releases()
        assignments = set()
        for release in releases:
            for member in release["record"]["changes"]:
                key = (release["record"]["component"], member["change_id"], member["intent_revision"])
                need(key not in assignments, "RELEASE_DUPLICATE", "Duplicate component/change revision assignment")
                assignments.add(key)
                path = self.store.path(f".roclec/changes/{member['change_id']}/revisions/{member['intent_revision']}/change.json")
                approved = read_json(path)
                need(approved.get("proposal_digest") == member["intent_revision"], "INVALID_REFERENCE", "Release member has no approved snapshot")
        from .causality import scoped_heads
        from .verification import Verification
        verifier = Verification(self)
        unfinished = []
        run_paths = sorted(self.store.path(".roclec/runs").glob("RUN-*/start.json"))
        groups, reports, runs = defaultdict(list), defaultdict(list), {}
        warnings = list(adr_warnings)
        def scope(record):
            return (record["change_id"], record["component"], (record.get("release") or {}).get("version"))
        for path in run_paths:
            started = verifier.read_start(path)
            groups[scope(started)].append(started)
            if (path.parent / "manifest.json").is_file():
                run = verifier.read_run(path.parent.name, started=started)
                runs[run["id"]] = run
                warnings.extend(verifier.log_issues(run))
            else:
                unfinished.append(path.parent.name)
        for (_, component, _), attempts in groups.items():
            actual = {c["id"]: c["argv"] for c in self.profile.components[component]["verification"]}
            for head in verifier.run_heads(attempts).get("run", []):
                recorded = {c["id"]: c["argv"] for c in head["checks"]}
                if actual != recorded:
                    issue = ModelError("CHECK_ARGV_CHANGED", "Configured check commands changed since this run",
                                       entity=head["id"]).issue
                    warnings.append({**issue, "severity": "warning"})
        for path in sorted(self.store.path(".roclec/evidence").glob("EVD-*.json")):
            report = verifier.read_evidence(path, runs)
            reports[scope(report)].append(report)
        for records in reports.values():
            scoped_heads(records, verifier.report_scopes)
        for path in self.store.path(".roclec/integrations").glob("*/*/*.json"):
            self.integration(path.parent.parent.name, path.parent.name, path.stem)
        from .releases import Releases
        for path in self.store.path(".roclec/releases").glob("*/*/preparations/*.json"):
            Releases(self).preparation(path.parent.parent.parent.name, path.parent.parent.name, path.stem)
        return {"profile_schema": 3, "current": current, "release_count": len(releases),
                "increment": "C3", "run_count": len(run_paths), "unfinished_runs": sorted(unfinished),
                "warnings": warnings,
                "candidate_verification": "check --gate verify; checks execute only with run verify"}

    def integration(self, change_id, component, proposal_digest=None):
        if proposal_digest is None:
            directory = self.store.path(f".roclec/integrations/{change_id}/{component}")
            records = sorted(directory.glob("*.json"))
            need(len(records) <= 1, "OPERATION_CONFLICT", "A component of a change cannot be integrated twice", exit_code=3)
            return self.integration(change_id, component, records[0].stem) if records else None
        path = self.store.path(f".roclec/integrations/{change_id}/{component}/{proposal_digest}.json")
        if not path.exists():
            return None
        record = self.read(path.relative_to(self.profile.root).as_posix())
        fields(record, ("model_schema", "change_id", "component", "proposal_digest", "run_id", "candidate", "evidence", "policy_id", "contracts", "digest",
                        "target_ref", "target_commit"), ("baseline_release",))
        need(text(record["target_ref"]) and record["target_ref"].startswith("refs/remotes/")
             and text(record["target_commit"]) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", record["target_commit"]),
             "INVALID_REFERENCE", "Integration requires a frozen target tracking ref and commit")
        need(record.get("change_id") == change_id and record.get("component") == component
             and record.get("proposal_digest") == proposal_digest
             and record.get("digest") == digest({k: v for k, v in record.items() if k != "digest"}),
             "HASH_MISMATCH", "Integration record integrity mismatch")
        identifier(record["run_id"], "RUN")
        from .verification import Verification
        run = Verification(self).read_run(record["run_id"])
        candidate = record["candidate"]
        need(run["status"] == "pass" and (run["change_id"], run["component"], run["candidate"]["inputs_digest"]) ==
             (change_id, component, candidate["inputs_digest"])
             and candidate["inputs_digest"] == digest(candidate["inputs"])
             and candidate["inputs"]["proposal_digest"] == proposal_digest,
             "INVALID_REFERENCE", "Integration does not reference its tested candidate")
        need(isinstance(record["contracts"], dict), "INVALID_INPUT", "Integration contracts must be a map", exit_code=2)
        for cap, revision in record["contracts"].items():
            self.contract(cap, revision)
        return record

    def preserve_integrated(self, record):
        """A rebase can approve pending work, never redefine a completed part."""
        directory = self.store.path(f".roclec/integrations/{record['id']}")
        completed = {c: self.integration(record["id"], c) for c in record["semantic"]["components"]}
        need(not all(completed.values()) or all(r["proposal_digest"] == record["proposal_digest"] for r in completed.values()),
             "INVALID_REFERENCE", "A fully integrated change is historical; propose a new change")
        for folder in directory.iterdir() if directory.exists() else []:
            component = folder.name
            integrated = self.integration(record["id"], component)
            need(component in record["semantic"]["components"], "INVALID_REFERENCE", "A pending revision cannot remove an integrated participant")
            if integrated["proposal_digest"] == record["proposal_digest"]:
                continue
            source = self.store.path(f".roclec/changes/{record['id']}/revisions/{integrated['proposal_digest']}")
            previous, _, _ = self.change(record["id"], source=source, historical=True)

            def projection(change, root):
                contracts = {}
                for base in change["semantic"]["bases"]:
                    if base["component"] == component and base["revision"]:
                        contracts[base["capability_id"]] = self.contract(base["capability_id"], base["revision"])
                for entry in change["semantic"]["proposed"]:
                    if component in entry["components"]:
                        path = root / f"proposed/{entry['capability_id']}/{entry['revision']}"
                        contracts[entry["capability_id"]] = self.contract(entry["capability_id"], entry["revision"], folder=path)
                result = {}
                for cap, (desc, contents) in contracts.items():
                    acs = {a["id"] for a in desc["acceptance"] if component in a["components"]}
                    result[cap] = {
                        "requirements": [{"id": r["id"], "text": sha(contents[r["statement"]]), "acceptance_ids": [a for a in r["acceptance_ids"] if a in acs]}
                                         for r in desc["requirements"] if component in r["components"]],
                        "acceptance": [{"id": a["id"], "text": sha(contents[a["scenario"]])} for a in desc["acceptance"] if a["id"] in acs],
                        "references": desc["references"],
                    }
                return result

            need(previous["kind"] == record["kind"] and projection(previous, source) ==
                 projection(record, self.store.path(f".roclec/changes/{record['id']}")),
                 "INVALID_REFERENCE", "An integrated obligation needs a new change; rebase only pending participants", entity=component)

    def views(self, write=False):
        current = self.current()["components"]
        caps = sorted({cap for capabilities in current.values() for cap in capabilities})
        writes, stale = {}, []
        for cap in caps:
            view = self.inspect_capability(cap)
            lines = [f"# {cap}", "", "Generated from integrated contract snapshots. Edit a change proposal to evolve this contract.", ""]
            for component, resolved in sorted(view["components"].items()):
                lines.extend([f"## {component}", "", f"Revision: `{resolved['revision']}`", ""])
                for req in resolved["requirements"]:
                    lines.extend([f"### {req['id']}", "", resolved["content"][req["statement"]].strip(), ""])
                    for ac in resolved["acceptance"]:
                        if ac["id"] in req["acceptance_ids"]:
                            lines.extend([f"#### {ac['id']}", "", resolved["content"][ac["scenario"]].strip(), ""])
            body = "\n".join(lines).encode("utf-8")
            rendered = f"<!-- roclec-managed-view sha256={sha(body)} -->\n".encode() + body
            relative = f"specs/capabilities/{cap}.md"
            path = self.store.path(relative)
            if path.exists():
                existing = path.read_bytes()
                if existing == rendered:
                    continue
                header, _, old_body = existing.partition(b"\n")
                need(header == f"<!-- roclec-managed-view sha256={sha(old_body)} -->".encode(),
                     "UNMANAGED_FILE", "View is unmanaged or has local edits; resolve them before regenerating", path=relative)
            stale.append(relative)
            writes[relative] = rendered
        if writes and write:
            receipt = self.store.apply("views", {"sources": current}, writes, self.token)
            return {"views": len(caps), "written": sorted(writes), "receipt": receipt}
        need(not stale, "VIEW_STALE", "Generated capability views need regeneration", actual=stale,
             remediation="views --write")
        return {"views": len(caps), "written": []}
