"""Profile-3 authorities, proposals, decisions and queries for C1/C2.

Verification and integration are separate services; publication belongs to C3.
"""
from __future__ import annotations

from pathlib import Path
from collections import defaultdict
from importlib.resources import files as package_files
import copy
import re
import subprocess

from . import flow as project_flow
from . import sessions as agent_sessions
from .adr import Adrs, adr_ids, declaration, in_folder, is_adr, supersession
from .config import Profile, load_profile, validate_profile
from .model import (ModelError, checked_files, digest, encoded, fields, fingerprint, identifier,
                    identities, local_path, need, read_json, schema, sha, strings, text,
                    validate_contract, validate_delta, version_key)
from .store import Store
from .origins import captured_paths, validate_coverage
from .rejection import Rejections, addresses, evaluations, is_stage, validate_decision

FOUNDATION_ROLES = {"context", "principles", "architecture", "stack", "engineering", "verification", "operations", "design", "process"}
REFERENCE_ID = r"[a-z][a-z0-9-]*"
# Section 7.6: a stage with ai = false is attributed, not proven.
HUMAN_STAGE_LIMITATION = ("Roclec records the actor declared in this stage's decisions; "
                          "it cannot prove who performed a stage with ai = false.")
STAGE_HOOKS = {stage: hook for hook, stage in project_flow.HOOKS.items()}
# TL.4: stages whose required agent session each change gate demands (cumulative through Kernel.gate).
# define and foundation are demanded at approve/agree and re-checked at implement, where the flow is the agreed one.
GATE_SESSIONS = {"implement": ("define", "design", "plan"), "verify": ("implement",), "integrate": ("implement", "verify", "review")}
# Decisions that may cite the agent sessions that produced them (TL.3).
SESSION_DECISIONS = {"change-approve", "change-cancel", "change-start", "foundation", "rejection", "checkpoint", "fut-decide"}
FUT_SCOPES = ("product", "process")


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
        # The flow is consumer-owned: seed it when absent, keep (after validating) an existing one.
        payload = {"profile": data}
        source = store.path(project_flow.FLOW_PATH)
        if source.is_file():
            flow_bytes = source.read_bytes()
        else:
            flow_bytes = package_files("roclec_spec_kit").joinpath("assets/project/flow.toml").read_bytes()
            writes[project_flow.FLOW_PATH] = flow_bytes
        flow = project_flow.parse(flow_bytes, profile.root)
        # Never overwrite an existing view at init; `views --write` owns regeneration.
        view = store.path(flow["view"])
        if not view.exists():
            # A new project has no records: its learning section is the empty projection.
            writes[flow["view"]] = project_flow.render(flow, profile.data)
            payload["flow_view"] = flow["view"]
        # The retrospective is consumer-owned like the flow: seeded when absent, never overwritten.
        retro = store.path(project_flow.RETRO_PATH)
        if flow["view"] != project_flow.RETRO_PATH and not retro.exists():
            writes[project_flow.RETRO_PATH] = package_files("roclec_spec_kit").joinpath("assets/project/flow-retro.md").read_bytes()
        ignore = store.path(".gitignore")
        ignored = ignore.read_bytes() if ignore.exists() else b""
        if b".roclec/runtime/" not in ignored.splitlines():
            writes[".gitignore"] = ignored + (b"\n" if ignored and not ignored.endswith(b"\n") else b"") + b".roclec/runtime/\n"
        def unchanged():
            need(view.exists() == ("flow_view" not in payload), "BASE_CONFLICT",
                 "Project inputs changed during validation", exit_code=3, path=flow["view"])
            need(project_flow.RETRO_PATH not in writes or not retro.exists(), "BASE_CONFLICT",
                 "Project inputs changed during validation", exit_code=3, path=project_flow.RETRO_PATH)
        receipt = store.apply("init", payload, writes, token, validate=unchanged)
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

    def _validate_references(self, record, *, writing=False):
        """Validate references.json; `writing` also requires a process reference to cover every component.

        Reading accepts a process reference that predates a newly configured component, so the
        project stays usable and `foundation check` reports that component as missing `process`.
        """
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
            if ref["role"] == "process":
                self._process_reference(ref, refs, writing=writing)
            refs[ref["id"]] = ref
        supersession(refs)
        return refs

    def _process_reference(self, ref, refs, *, writing):
        every = sorted(self.profile.components)
        command = (f"reference add {ref['id']} --path {project_flow.FLOW_PATH} --role process "
                   + " ".join(f"--component {c}" for c in every))
        other = [r["id"] for r in refs.values() if r["role"] == "process"]
        need(not other, "INVALID_REFERENCE", "Only one process reference may exist", entity=ref["id"],
             actual=sorted(other + [ref["id"]]), remediation=f"Keep the single process reference {other[0] if other else ''}; "
             "use reference update to change it.")
        need(ref["path"] == project_flow.FLOW_PATH, "INVALID_REFERENCE", "The process reference must be the project flow",
             entity=ref["id"], expected=project_flow.FLOW_PATH, actual=ref["path"], remediation=command)
        need(not writing or sorted(ref["components"]) == every, "INVALID_REFERENCE",
             "The process reference must apply to every configured component", entity=ref["id"],
             expected=every, actual=sorted(ref["components"]), remediation=command)

    def _flow(self):
        """Return (parsed flow, raw bytes) from one read; FLOW_MISSING or FLOW_INVALID otherwise."""
        path = self.store.path(project_flow.FLOW_PATH)
        if not path.is_file():
            project_flow.load(self.profile.root)  # Raises FLOW_MISSING with its remediation.
        raw = path.read_bytes()
        return project_flow.parse(raw, self.profile.root), raw

    def _evaluate(self, point, criteria, outcome, flow=None):
        """Evaluate a decision's criteria against the current flow; return (criteria, flow sha256).

        Exactly the criteria declared for `point` (D28); the sha pins the flow bytes evaluated.
        """
        if flow is None:
            flow = self._flow()
        parsed, raw = flow
        rows = project_flow.evaluate(parsed, point, [] if criteria is None else criteria, outcome=outcome)
        return rows, sha(raw)

    def _cited(self, sessions, **scope):
        """The `sessions` key of a new decision: validated citations, omitted when none (TL.3)."""
        cited = agent_sessions.cite(self, list(sessions or ()), **scope)
        return {"sessions": cited} if cited else {}

    def require_session(self, stage, parsed, *, change_id=None, component=None, subject=None, release=None,
                        any_component=False, sessions=None):
        """SESSION_REQUIRED unless `stage` is optional in `parsed` or a session cites its scope (TL.4).

        Any session of that stage and scope counts; it is not bound to digests or candidates.
        Returns the matching session IDs, or None when the stage does not require one.
        """
        row = next(r for r in parsed["stages"] if r["name"] == stage)
        if row["session_evidence"] != "required":
            return None
        if sessions is None:
            from .verification import Verification
            sessions = Verification(self).sessions(change_id)
        found = [s["id"] for s in sessions if agent_sessions.matches(s, stage, change_id=change_id, component=component,
                                                                     subject=subject, release=release,
                                                                     any_component=any_component)]
        if found:
            return found
        entity = (subject if stage == "foundation" else f"{release['component']}/{release['version']}" if stage == "release"
                  else "/".join(filter(None, (change_id, component))))
        raise ModelError("SESSION_REQUIRED", f"The {stage} stage requires an agent session", entity=entity, expected=stage,
                         path=project_flow.FLOW_PATH,
                         remediation=agent_sessions.required_hint(stage, change_id=change_id, component=component,
                                                                  subject=subject, release=release)
                         + f' Or set session_evidence = "optional" on [stages.{stage}] and agree the flow again.')

    def require_gate_sessions(self, change_id, component, gate, parsed=None, *, subjects=()):
        """Sessions a change gate demands for one component (GATE_SESSIONS); a disabled review needs none.

        `subjects` are the foundation references the component depends on: with a required foundation
        stage, each needs its session (re-checked at implement, where the flow bytes are agreed).
        """
        if parsed is None:
            parsed = self._flow()[0]
        required = {row["name"] for row in parsed["stages"] if row["session_evidence"] == "required"}
        stages = [stage for stage in GATE_SESSIONS[gate] if stage in required]
        subjects = sorted(subjects) if "foundation" in required else []
        if not stages and not subjects:
            return  # Nothing demanded: session records are not even read.
        from .verification import Verification
        verifier = Verification(self)
        if subjects:
            every = verifier.sessions()
            for subject in subjects:
                self.require_session("foundation", parsed, subject=subject, sessions=every)
        sessions = verifier.sessions(change_id)
        for stage in stages:
            if stage == "design" and not self.profile.components[component]["user_facing"]:
                continue
            if stage == "review" and not verifier.policy(change_id)["enabled"]:
                continue
            self.require_session(stage, parsed, change_id=change_id, component=component,
                                 any_component=stage in {"define", "plan"}, sessions=sessions)

    def write_reference(self, action, ref_id, path, components, role, supersedes=()):
        refs = self.references()
        if action == "update" and ref_id in refs:
            Rejections(self).withdrawn("adr" if refs[ref_id]["role"] == "decision" else "reference", ref_id)
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
        self._validate_references(record, writing=True)
        folder = self.profile.adr["path"]
        need(role != "decision" or in_folder(path, folder), "INVALID_PATH",
             "An ADR must be a Markdown file inside the configured ADR folder", exit_code=2, entity=ref_id,
             expected=folder, actual=path, remediation="Place the ADR under the [adr] path of the profile (default docs/adr).")
        source = self.store.path(path)
        need(source.is_file() and bool(source.read_bytes().strip()), "INVALID_REFERENCE",
             "Reference requires an existing nonempty source", path=path)
        if role == "process":
            project_flow.parse(source.read_bytes(), self.profile.root)
        receipt = self.store.apply("reference-" + action, {"id": ref_id},
                                   {".roclec/references.json": encoded(record)}, self.token)
        return {"reference": ref, "receipt": receipt}

    def reject(self, subject_type, entity, subject_digest, actor, reason, *, consequence=None, corrections=(), fut=None,
               criteria=None, addresses=None, sessions=()):
        need(subject_type in project_flow.SUBJECT_POINTS, "INVALID_INPUT", "Unknown rejection subject", exit_code=2)
        service = Rejections(self)
        if subject_type == "change":
            need(not any(d["kind"] == "change-cancel" for d in self.decisions(entity)), "CHANGE_CANCELED",
                 "Canceled work requires a new change", entity=entity)
            current, _, _ = self.change(entity)
            self._cancelable_components(current)
        service.withdrawn(subject_type, entity)
        fingerprint(subject_digest)
        need(text(actor) and text(reason), "INVALID_INPUT", "Actor and reason are required", exit_code=2)
        flow = self._flow()
        point = project_flow.SUBJECT_POINTS[subject_type]
        if consequence is None:
            # The flow declares the default consequence of rejecting at this point.
            consequence = project_flow.point(flow[0], point)["on_reject"]
        need(consequence in {"revise", "cancel", "defer"}, "INVALID_INPUT", "Unknown rejection consequence", exit_code=2)
        from .rejection import corrections as validate_corrections
        validate_corrections(corrections, consequence)
        need((consequence == "defer") == (fut is not None), "INVALID_INPUT", "Only defer requires a FUT", exit_code=2)
        if fut is not None:
            self.inspect_fut(fut)
        pin, files = service.subject(subject_type, entity)
        need(pin == subject_digest, "APPROVAL_STALE", "Rejection must cite the current subject digest", expected=pin, actual=subject_digest)
        evaluated, flow_pin = self._evaluate(point, criteria, "rejected", flow)
        subject = {"type": subject_type, "entity": entity, "digest": pin}
        extra = {"subject": subject, "consequence": consequence, "corrections": list(corrections),
                 "criteria": evaluated, "flow": flow_pin, "files": {p: sha(b) for p, b in files.items()}}
        if fut is not None:
            extra["fut"] = fut
        if addresses is not None:
            service.require_addresses(subject_type, entity, pin, addresses)
            extra["addresses"] = addresses
        # A change rejection cites that change's sessions, an ADR or reference rejection its foundation
        # sessions; a prototype rejection any recorded session.
        scope = ({"change_id": entity} if subject_type == "change" else
                 {"subject": entity} if subject_type in {"adr", "reference"} else {})
        extra.update(self._cited(sessions, **scope))
        decision, path = self._decision("rejection", entity, actor, reason, **extra)
        writes = {path: encoded(decision)}
        for relative, data in files.items():
            target = f"{service.root(subject)}/{relative}"
            need(not self.store.path(target).exists() or self.store.path(target).read_bytes() == data,
                 "HASH_MISMATCH", "Rejected snapshot was modified", path=target)
            writes[target] = data
        result = {"decision": decision}
        if subject_type == "change" and consequence == "cancel":
            record, _, _ = self.change(entity)
            pending = self._cancelable_components(record)
            cancellation, _ = self._decision("change-cancel", entity, actor, reason,
                                                       proposal_digest=pin, components=pending)
            cancellation["previous"] = decision["id"]
            cancellation["id"] = digest({k: v for k, v in cancellation.items() if k != "id"})
            writes[f".roclec/decisions/{cancellation['id']}.json"] = encoded(cancellation)
            result["cancellation"] = cancellation
        if subject_type == "prototype":
            # The paired checkpoint repeats the rejection's evaluation; decisions() checks they match.
            checkpoint, _ = self._decision("checkpoint", entity, actor, reason, subject=subject, outcome="rejected",
                                           rejection=decision["id"], criteria=evaluated, flow=flow_pin)
            checkpoint["previous"] = decision["id"]
            checkpoint["id"] = digest({k: v for k, v in checkpoint.items() if k != "id"})
            writes[f".roclec/decisions/{checkpoint['id']}.json"] = encoded(checkpoint)
            result["checkpoint"] = checkpoint
        source_guards = {entity: pin} if subject_type == "prototype" else {}
        result["receipt"] = self.store.apply("reject", {"id": entity, "subject": subject, "source_guards": source_guards}, writes, self.token)
        return result

    def checkpoint(self, entity, subject_digest, actor, reason, *, outcome, addresses=None, criteria=None, sessions=()):
        need(outcome == "approved", "INVALID_INPUT", "Use reject prototype with corrections for a rejected checkpoint", exit_code=2)
        service = Rejections(self)
        pin, _ = service.subject("prototype", entity)
        need(pin == subject_digest, "APPROVAL_STALE", "Checkpoint must cite current prototype bytes", expected=pin, actual=subject_digest)
        service.require_addresses("prototype", entity, pin, addresses)
        evaluated, flow_pin = self._evaluate("design", criteria, outcome)
        extra = {"addresses": addresses} if addresses is not None else {}
        extra.update(self._cited(sessions))
        decision, path = self._decision("checkpoint", entity, actor, reason,
                                        subject={"type": "prototype", "entity": entity, "digest": pin}, outcome=outcome,
                                        criteria=evaluated, flow=flow_pin, **extra)
        receipt = self.store.apply("checkpoint", {"id": entity, "source_guards": {entity: pin}}, {path: encoded(decision)}, self.token)
        return {"decision": decision, "receipt": receipt}

    def _stage_checkpoints(self, change_id, hook, component, decisions=None):
        decisions = self.decisions(change_id) if decisions is None else decisions
        return [d for d in decisions if d["entity"] == change_id and is_stage(d)
                and d["hook"] == hook and d["component"] == component]

    def stage_checkpoint(self, change_id, hook, component, subject_digest, actor, reason, *, outcome, criteria=None,
                         run=None, consequence=None, corrections=(), fut=None, addresses=None, sessions=()):
        """Human decision at a flow hook on one change component (section 7.3).

        Subjects are immutable records: the proposal (pre-implement), a passed run candidate
        (pre-integrate) or the integration record (handoff). A rejection is the same decision
        with outcome rejected; `cancel` pairs a change-cancel for this component in one operation.
        """
        need(hook in project_flow.HOOKS, "INVALID_INPUT", "Unknown checkpoint hook", exit_code=2,
             expected=sorted(project_flow.HOOKS), actual=hook)
        need(outcome in {"approved", "rejected"}, "INVALID_INPUT", "outcome must be approved or rejected", exit_code=2)
        need((run is not None) == (hook == "pre-integrate"), "INVALID_INPUT",
             "--run is required for pre-integrate and applies to no other hook", exit_code=2)
        need(outcome == "rejected" or (consequence is None and not corrections and fut is None), "INVALID_INPUT",
             "Rejection details apply only to a rejected checkpoint", exit_code=2)
        need(text(actor) and text(reason), "INVALID_INPUT", "Actor and reason are required", exit_code=2)
        record, _, _ = self.change(change_id)
        self._component(record, component)
        entity = f"{change_id}/{component}/{hook}"
        decisions = self.decisions(change_id)
        need(not any(d["kind"] == "change-cancel" and component in d["components"] for d in decisions),
             "CHANGE_CANCELED", "Canceled work requires a new change", entity=change_id)
        flow = self._flow()
        point = project_flow.point(flow[0], hook)
        stage = project_flow.HOOKS[hook]
        need(point is not None, "INVALID_REFERENCE", f"The current flow declares no {hook} checkpoint", entity=entity,
             path=project_flow.FLOW_PATH, remediation=f"Declare checkpoint on [stages.{stage}] and agree the flow, "
             "or record nothing: an undeclared hook blocks nothing.")
        if hook == "pre-implement":
            self._approved(record)
            pin = record["proposal_digest"]
        elif hook == "pre-integrate":
            from .verification import Verification
            identifier(run, "RUN")
            attempt = Verification(self).read_run(run)
            need(attempt.get("release") is None and (attempt["change_id"], attempt["component"]) == (change_id, component),
                 "INVALID_REFERENCE", "Run belongs to another change, component or a release", entity=run)
            need(attempt["status"] == "pass", "CANDIDATE_INCOMPLETE", "Run did not pass", entity=run, actual=attempt["status"])
            need(attempt["candidate"]["inputs"]["proposal_digest"] == record["proposal_digest"], "EVIDENCE_STALE",
                 "Run tested another proposal revision", entity=run)
            pin = attempt["candidate"]["inputs_digest"]
        else:
            integration = self.integration(change_id, component)
            need(integration is not None, "INVALID_REFERENCE", "Handoff needs the integrated component", entity=entity,
                 remediation=f"Integrate first: roclec integrate prepare {change_id} --component {component} ...")
            pin = integration["digest"]
        fingerprint(subject_digest)
        need(subject_digest == pin, "APPROVAL_STALE", "Checkpoint must cite the current subject digest", entity=entity,
             expected=pin, actual=subject_digest)
        extra = {}
        if outcome == "rejected":
            consequence = consequence or point["on_reject"]
            need(consequence in {"revise", "cancel", "defer"}, "INVALID_INPUT", "Unknown rejection consequence", exit_code=2)
            # The integration record is immutable and integrated work is never canceled: QA findings go
            # to a follow-up fix change captured as a FUT, and the change may leave its planning release.
            need(hook != "handoff" or consequence == "defer", "INVALID_INPUT",
                 "A handoff rejection can only defer to a follow-up change", exit_code=2, entity=entity, actual=consequence,
                 remediation="Capture the follow-up fix as a FUT and reject with --consequence defer --fut FUT-NNN; "
                             "then remove the change from the planning release with release plan if it must not ship.")
            from .rejection import corrections as validate_corrections
            validate_corrections(corrections, consequence)
            need((consequence == "defer") == (fut is not None), "INVALID_INPUT", "Only defer requires a FUT", exit_code=2)
            if fut is not None:
                self.inspect_fut(fut)
                extra["fut"] = fut
            if consequence == "cancel":
                pending = self._cancelable_components(record)
                need(component in pending, "INVALID_REFERENCE", "Integrated work requires a reversal change", entity=entity,
                     remediation="Propose a new change that reverses the integrated behavior.")
            extra.update(consequence=consequence, corrections=list(corrections))
        prior = [d for d in self._stage_checkpoints(change_id, hook, component, decisions) if d["outcome"] == "rejected"]
        Rejections.require_stage(prior, pin, addresses, approving=outcome == "approved", entity=entity)
        if addresses is not None:
            extra["addresses"] = addresses
        if run is not None:
            extra["run"] = run
        extra.update(self._cited(sessions, change_id=change_id))
        evaluated, flow_pin = self._evaluate(hook, criteria, outcome, flow)
        subject = {"type": "stage", "entity": change_id, "digest": pin}
        decision, path = self._decision("checkpoint", change_id, actor, reason, subject=subject, hook=hook,
                                        component=component, outcome=outcome, criteria=evaluated, flow=flow_pin, **extra)
        writes = {path: encoded(decision)}
        result = {"decision": decision}
        if outcome == "rejected" and consequence == "cancel":
            cancellation, cancel_path = self._decision("change-cancel", change_id, actor, reason,
                                                       proposal_digest=record["proposal_digest"], components=[component])
            writes[cancel_path] = encoded(cancellation)
            result["cancellation"] = cancellation
        result["receipt"] = self.store.apply("checkpoint", {"id": change_id, "hook": hook, "component": component,
                                                            "subject": subject}, writes, self.token)
        return result

    def require_checkpoint(self, change_id, component, hook, pin, *, run=None):
        """CHECKPOINT_REQUIRED unless the current flow leaves `hook` undeclared or it is approved on `pin`."""
        point = project_flow.point(self._flow()[0], hook)
        if point is None:
            return None
        chain = self._stage_checkpoints(change_id, hook, component)
        rows = [d for d in chain if d["subject"]["digest"] == pin]
        # An approval only counts after the latest revise rejection of this hook/component: an older
        # approval of these same bytes cannot bypass corrections requested on a later subject. Any
        # approval recorded after that rejection had to address it (Rejections.require_stage).
        revise = [index for index, d in enumerate(chain) if d["outcome"] == "rejected" and d["consequence"] == "revise"]
        if rows and rows[-1]["outcome"] == "approved" and chain.index(rows[-1]) > max(revise, default=-1):
            return rows[-1]
        subject = {"pre-implement": "proposal", "pre-integrate": "run candidate", "handoff": "integration record"}[hook]
        evaluation = (f" --criteria <JSON evaluating {', '.join(point['criteria'])}>" if point["criteria"] else "")
        command = (f"roclec checkpoint {change_id} --hook {hook} --component {component} --digest {pin}"
                   + (f" --run {run}" if run else "") + " --outcome approved --actor <person> --reason <why>" + evaluation)
        raise ModelError("CHECKPOINT_REQUIRED", f"The {hook} checkpoint needs an approval of the current {subject}",
                         entity=f"{change_id}/{component}/{hook}", expected=pin,
                         actual=rows[-1]["outcome"] if rows else None,
                         remediation=f"Ask the {point['decider']} to decide, then record it: {command}")

    def _handoff_deferred(self, change_id, component, integration, decisions=None):
        """True when the latest handoff checkpoint on this integration record is a deferred rejection."""
        rows = [d for d in self._stage_checkpoints(change_id, "handoff", component, decisions)
                if d["subject"]["digest"] == integration["digest"]]
        return bool(rows) and rows[-1]["outcome"] == "rejected" and rows[-1]["consequence"] == "defer"

    def agreed_flow(self, component):
        """FOUNDATION_INCOMPLETE unless the process reference of `component` is agreed on the current flow bytes."""
        parsed, raw = self._flow()
        refs = [r for r in self.references().values() if r["role"] == "process" and component in r["components"]]
        every = " ".join(f"--component {c}" for c in sorted(self.profile.components))
        need(bool(refs), "FOUNDATION_INCOMPLETE", "Missing agreed process reference", entity=component,
             remediation=f"roclec reference add flow --path {project_flow.FLOW_PATH} --role process {every}, then "
                         "roclec foundation agree --ref flow with the user.")
        ref = refs[0]
        agree = (f"Agree the current flow with the user: roclec foundation agree --ref {ref['id']} --actor <person> "
                 "--reason <why> --criteria <JSON evaluating the foundation criteria>.")
        decision = self.read(f".roclec/decisions/{ref['decision_id']}.json") if ref["decision_id"] else None
        need(decision is not None and decision.get("kind") == "foundation" and decision.get("status") == "agreed"
             and (decision.get("sources") or {}).get(ref["id"]) == sha(raw)
             and Rejections(self).state("reference", ref["id"], sha(raw), approved=True) == "approved",
             "FOUNDATION_INCOMPLETE", "The project flow changed since its agreement", entity=ref["id"],
             path=project_flow.FLOW_PATH, remediation=agree)
        return parsed

    def inspect_reference(self, ref_id):
        ref = self.references().get(ref_id)
        need(ref is not None, "INVALID_REFERENCE", "Unknown reference", entity=ref_id)
        kind = "adr" if ref["role"] == "decision" else "reference"
        source = self.store.path(ref["path"])
        pin = sha(source.read_bytes()) if source.is_file() else None
        agreements = [d for d in self.decisions(ref_id) if d["kind"] == "foundation"]
        approved = bool(agreements and agreements[-1]["sources"][ref_id] == pin and ref["decision_id"] == agreements[-1]["id"])
        service = Rejections(self)
        return {"reference": ref, "sha256": pin, "state": service.state(kind, ref_id, pin, approved=approved),
                "rejections": service.history(kind, ref_id), "decisions": self.decisions(ref_id)}

    def inspect_prototype(self, entity):
        source = self.store.path(entity)
        pin = sha(source.read_bytes()) if source.is_file() else None
        decisions = self.decisions(entity)
        checkpoints = [d for d in decisions if d["kind"] == "checkpoint" and d["subject"]["type"] == "prototype"]
        approved = bool(checkpoints and checkpoints[-1]["outcome"] == "approved" and checkpoints[-1]["subject"]["digest"] == pin)
        service = Rejections(self)
        return {"path": entity, "sha256": pin, "state": service.state("prototype", entity, pin, approved=approved),
                "checkpoint": checkpoints[-1] if checkpoints else None,
                "rejections": service.history("prototype", entity), "decisions": decisions}

    def _list_rejections(self, *, open_only=False):
        result = []
        seen = set()
        for decision in self.decisions():
            if decision["kind"] != "rejection":
                continue
            kind, entity = decision["subject"]["type"], decision["entity"]
            if (kind, entity) in seen:
                continue
            seen.add((kind, entity))
            value, pin = None, None
            if kind == "change":
                record, _, _ = self.change(entity)
                value, pin = record["semantic"].get("addresses"), record["proposal_digest"]
            result.extend(row for row in Rejections(self).history(kind, entity, value=value, pin=pin)
                          if not open_only or row["open"])
        for entity in sorted({d["entity"] for d in self.decisions() if is_stage(d) and d["outcome"] == "rejected"}):
            result.extend(row for row in Rejections(self).stage_history(entity) if not open_only or row["open"])
        return sorted(result, key=lambda row: (row["entity"], row["id"]))

    def _prototypes(self, value):
        need(isinstance(value, list), "INVALID_INPUT", "prototypes must be a list", exit_code=2)
        paths = []
        for row in value:
            fields(row, ("path", "sha256"))
            self.store.path(row["path"])
            fingerprint(row["sha256"])
            paths.append(row["path"])
        need(paths == sorted(set(paths)), "INVALID_INPUT", "Prototype paths must be unique and sorted", exit_code=2)

    def _prototype_gate(self, record):
        for entry in record["semantic"].get("prototypes", []):
            view = self.inspect_prototype(entry["path"])
            need(view["state"] == "approved" and view["sha256"] == entry["sha256"], "PROTOTYPE_NOT_APPROVED",
                 "Cited prototype needs approval on its current pinned bytes", path=entry["path"], actual=view["state"])

    def agree_foundation(self, ref_id, actor, reason, *, addresses=None, criteria=None, sessions=(), futs=()):
        need(text(actor) and text(reason), "INVALID_INPUT", "Actor and reason are required", exit_code=2)
        refs = self.references()
        need(ref_id in refs, "INVALID_REFERENCE", "Unknown foundation reference", entity=ref_id)
        ref = refs[ref_id]
        source = self.store.path(ref["path"])
        need(source.is_file(), "FOUNDATION_INCOMPLETE", "Reference source is missing", path=ref["path"])
        content = source.read_bytes()
        need(bool(content.strip()), "FOUNDATION_INCOMPLETE", "Reference source is empty", path=ref["path"])
        if ref["role"] == "process":
            # Agreement freezes exactly these bytes, so they must be a valid flow.
            project_flow.parse(content, self.profile.root)
        Rejections(self).require_addresses("adr" if ref["role"] == "decision" else "reference", ref_id, sha(content), addresses)
        flow = self._flow()
        evaluated, flow_pin = self._evaluate("foundation", criteria, "approved", flow)
        extra = {"supersedes": list(ref["supersedes"])} if ref["role"] == "decision" else {}
        if addresses is not None:
            extra["addresses"] = addresses
        cited = self._process_futs(ref, futs)
        if cited:
            extra["futs"] = cited
        extra.update(self._cited(sessions, subject=ref_id))
        self.require_session("foundation", flow[0], subject=ref_id)
        decision, path = self._decision("foundation", ref_id, actor, reason, status="agreed", sources={ref_id: sha(content)},
                                        criteria=evaluated, flow=flow_pin, **extra)
        decision_id = decision["id"]
        ref["decision_id"] = decision_id
        writes = {".roclec/references.json": encoded({"model_schema": 2, "references": [refs[k] for k in sorted(refs)]}),
                  path: encoded(decision)}
        receipt = self.store.apply("foundation-agree", {"id": ref_id}, writes, self.token)
        return {"reference": ref, "decision": decision, "receipt": receipt}

    def _process_futs(self, ref, futs):
        """FUTs a process agreement addresses (TL.5): captured or evaluating process FUTs, sorted and unique."""
        if not futs:
            return []
        need(ref["role"] == "process", "INVALID_INPUT", "Only an agreement of the process reference cites FUTs", exit_code=2,
             entity=ref["id"], actual=ref["role"],
             remediation="Remove --fut, or cite the process FUTs when agreeing the flow reference.")
        result = sorted(set(futs))
        for fut_id in result:
            identifier(fut_id, "FUT")
            need(self.store.path(f".roclec/futs/{fut_id}.json").is_file(), "INVALID_REFERENCE", "Unknown FUT", exit_code=2,
                 entity=fut_id, remediation="Capture the friction first with fut capture --file FILE (scope process).")
            view = self.inspect_fut(fut_id)
            need(view["scope"] == "process", "INVALID_REFERENCE", "A flow agreement cites only process FUTs", exit_code=2,
                 entity=fut_id, actual=view["scope"],
                 remediation="Cite FUTs captured with scope process; a product FUT is promoted to a change.")
            need(view["status"] in {"captured", "evaluating"}, "INVALID_REFERENCE", "The cited FUT is already resolved",
                 exit_code=2, entity=fut_id, actual=view["status"],
                 remediation="Reopen it with fut decide --outcome evaluating, or cite an open process FUT.")
        return result

    def foundation(self, component, change=None):
        self.profile.repo(component)
        refs = self.references()
        roles, resolved, issues = set(), [], []
        invalid_flow = False
        decisions = self.decisions()
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
                fields(decision, ("model_schema", "id", "kind", "entity", "previous", "status", "actor", "reason", "sources"),
                       ("addresses", "criteria", "flow", "sessions", "futs"))
                need(decision["id"] == ref["decision_id"] and decision["kind"] == "foundation"
                     and decision["status"] == "agreed" and text(decision["actor"]) and text(decision["reason"]),
                     "FOUNDATION_INCOMPLETE", "Reference decision is not agreed", entity=ref["id"])
                need(isinstance(decision["sources"], dict) and decision["sources"].get(ref["id"]) == sha(path.read_bytes()),
                     "FOUNDATION_INCOMPLETE", "Reference changed since its agreement", entity=ref["id"])
                state = Rejections(self).state("reference", ref["id"], sha(path.read_bytes()), approved=True, decisions=decisions)
                need(state == "approved", "FOUNDATION_INCOMPLETE", "Foundation reference was rejected or withdrawn", entity=ref["id"])
                if ref["role"] == "process":
                    # Agreed bytes can still fail later checks (e.g. a deleted agent binding).
                    invalid_flow = True
                    project_flow.parse(path.read_bytes(), self.profile.root)
                    invalid_flow = False
                roles.add(ref["role"])
                resolved.append({**ref, "sha256": sha(path.read_bytes())})
            except ModelError as exc:
                issues.append(exc.issue)
        required = {"context", "principles", "architecture", "stack", "engineering", "verification", "process"}
        if self.profile.components[component]["user_facing"]:
            required.add("design")
        if invalid_flow:
            roles.add("process")  # Already reported as FLOW_INVALID, not as missing.
        for role in sorted(required - roles):
            remediation = (f"Run `roclec skills` if {project_flow.FLOW_PATH} is missing, then `roclec reference add flow "
                           f"--path {project_flow.FLOW_PATH} --role process "
                           + " ".join(f"--component {c}" for c in sorted(self.profile.components))
                           + "` and `roclec foundation agree --ref flow` with the user.") if role == "process" else None
            issues.append(ModelError("FOUNDATION_INCOMPLETE", f"Missing agreed {role} reference", entity=component,
                                     remediation=remediation).issue)
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
               ("baseline_release", "fixes", "origins", "coverage", "architecture_decisions", "addresses", "prototypes",
                "sessions"))
        if "addresses" in semantic:
            addresses(semantic["addresses"])
        if "sessions" in semantic:
            # Shape only on read; existence and scope are checked when the bundle is sealed or imported.
            agent_sessions.ids(semantic["sessions"])
        self._prototypes(semantic.get("prototypes", []))
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
        need(not any(Path(p).parts[0] in {"proposed", "revisions", "rejected"} for p in content),
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
        existing = self.store.path(destination).exists()
        need(not existing or Rejections(self).revising(change_id), "ID_COLLISION", "Change ID already exists", entity=change_id)
        record, files, new_ids = self.change(change_id, source=source_file.parent, check_base=True)
        agent_sessions.cite(self, record["semantic"].get("sessions"), change_id=change_id)
        if existing:
            Rejections(self).require_addresses("change", change_id, record["proposal_digest"], record["semantic"].get("addresses"))
            self.preserve_integrated(record)
        registry = self.registry()
        registry["identities"].update(new_ids)
        writes = {f"{destination}/{p}": b for p, b in files.items()}
        writes[".roclec/identities.json"] = encoded(registry)
        receipt = self.store.apply("change-new", {"id": change_id, "proposal_digest": record["proposal_digest"]}, writes, self.token)
        return {"change": record, "status": "draft", "receipt": receipt}

    @staticmethod
    def _decision_chain(record):
        """Chains order decisions and detect forks from merged histories.

        Change-level decisions share (CHG, None); each component's start is (CHG, component) because
        starts happen on feature branches. Hook checkpoints are trunk-only but per component: they
        chain on (CHG, "checkpoint:<component>"), so one component's hooks never fork with another
        component's hooks, with the change's approvals or with a start recorded on a branch.
        """
        if record["kind"] == "change-start":
            return (record["entity"], record.get("component"))
        if record["kind"] == "checkpoint" and (record.get("subject") or {}).get("type") == "stage":
            return (record["entity"], f"checkpoint:{record.get('component')}")
        return (record["entity"], None)

    def decisions(self, entity=None):
        chains = defaultdict(dict)
        directory = self.store.path(".roclec/decisions")
        records, seen = [], set()
        for path in sorted(directory.glob("*.json")) if directory.exists() else []:
            record = self.read(path.relative_to(self.profile.root).as_posix())
            fields(record, ("model_schema", "id", "kind", "entity", "previous", "actor", "reason"),
                   ("proposal_digest", "component", "components", "outcome", "target", "enabled", "status", "sources", "supersedes", "subject", "consequence", "corrections", "criteria", "fut", "files", "addresses", "rejection", "flow",
                    "hook", "run", "sessions", "futs"))
            fingerprint(record["id"])
            need(record["id"] not in seen, "ID_COLLISION", "Duplicate decision digest", entity=record["id"])
            seen.add(record["id"])
            records.append((path, record))
        for path, record in records:
            need(record["id"] == path.stem and record["id"] == digest({k: v for k, v in record.items() if k != "id"}),
                 "HASH_MISMATCH", "Decision digest does not match its record", path=path.name)
            need(record["kind"] in {"change-approve", "change-start", "change-cancel", "fut-decide", "review-policy", "foundation", "rejection", "checkpoint"}
                 and text(record["actor"]) and text(record["reason"]), "INVALID_INPUT", "Invalid decision record", exit_code=2)
            if record["previous"] is not None:
                fingerprint(record["previous"])
            if record["kind"] in {"rejection", "checkpoint"}:
                validate_decision(record)
                if is_stage(record):
                    need(record["component"] in self.profile.components, "INVALID_REFERENCE", "Unknown checkpoint component",
                         entity=record["id"])
            elif record["kind"].startswith("change-") or record["kind"] == "review-policy":
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
            # Decisions evaluated against the flow pin its bytes and record their criteria (D28). Records
            # made before FF keep neither: they stay valid and are never re-evaluated against today's flow.
            evaluated = {"change-approve", "foundation", "checkpoint", "rejection"}
            if "flow" in record:
                need(record["kind"] in evaluated, "INVALID_INPUT", "Only an evaluated decision pins the flow",
                     exit_code=2, path=path.name)
                fingerprint(record["flow"])
            if "criteria" in record:
                need(record["kind"] in evaluated, "INVALID_INPUT", "Only an evaluated decision records criteria",
                     exit_code=2, path=path.name)
                evaluations(record["criteria"], approved=record["kind"] != "rejection" and record.get("outcome") != "rejected")
            need(not {"hook", "run"} & record.keys() or (record["kind"] == "checkpoint" and is_stage(record)),
                 "INVALID_INPUT", "Only a hook checkpoint names a hook or run", exit_code=2, path=path.name)
            need("supersedes" not in record or (record["kind"] == "foundation" and is_adr(record["entity"])),
                 "INVALID_INPUT", "Only an ADR agreement records supersedes", exit_code=2, path=path.name)
            if "addresses" in record:
                addresses(record["addresses"])
            if "sessions" in record:
                need(record["kind"] in SESSION_DECISIONS, "INVALID_INPUT", "This decision cannot cite agent sessions",
                     exit_code=2, path=path.name)
                agent_sessions.ids(record["sessions"])
            if "futs" in record:
                need(record["kind"] == "foundation" and not is_adr(record["entity"]), "INVALID_INPUT",
                     "Only a process agreement cites FUTs", exit_code=2, path=path.name)
                for fut_id in strings(record["futs"], nonempty=True):
                    identifier(fut_id, "FUT")
            chain = self._decision_chain(record)
            previous = record["previous"]
            existing = chains[chain].get(previous)
            need(existing is None, "DECISION_FORK", "Two decisions have the same predecessor in a chain",
                 entity="/".join(filter(None, chain)),
                 expected=previous, actual=sorted([existing["id"], record["id"]]) if existing else None)
            chains[chain][previous] = record
        by_id = {record["id"]: record for _, record in records}
        for path, record in records:
            if record["kind"] == "checkpoint" and "rejection" in record and {"criteria", "flow"} & record.keys():
                paired = by_id.get(record["rejection"])
                need(paired is not None and paired["kind"] == "rejection"
                     and all(record.get(key) == paired.get(key) for key in ("criteria", "flow")),
                     "INVALID_REFERENCE", "Paired checkpoint evaluation differs from its rejection", entity=record["id"],
                     path=path.name)
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

    def approve(self, change_id, proposal_digest, actor, reason, *, criteria=None, sessions=()):
        record, files, new_ids = self.change(change_id, check_base=True)
        self.preserve_integrated(record)
        need(not any(d["kind"] == "change-cancel" for d in self.decisions(change_id)),
             "CHANGE_CANCELED", "Canceled work requires a new change", entity=change_id)
        need(proposal_digest == record["proposal_digest"], "APPROVAL_STALE", "Approval must cite the exact proposal digest")
        self._origin_approval(record)
        Rejections(self).require_addresses("change", change_id, proposal_digest, record["semantic"].get("addresses"))
        Adrs(self).approvable(record)
        # The approval records the flow it was given under and the evaluation of its criteria;
        # agreement of that flow is enforced at implement.
        flow = self._flow()
        evaluated, flow_pin = self._evaluate("approve", criteria, "approved", flow)
        self.require_session("define", flow[0], change_id=change_id)
        extra = {"addresses": record["semantic"]["addresses"]} if "addresses" in record["semantic"] else {}
        extra.update(self._cited(sessions, change_id=change_id))
        decision, path = self._decision("change-approve", change_id, actor, reason, proposal_digest=proposal_digest,
                                        criteria=evaluated, flow=flow_pin, **extra)
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
        decisions = self.decisions(change["id"])
        history = [d for d in decisions if d["kind"] == "rejection" and d["subject"]["type"] == "change"]
        need(not history or decisions.index(history[-1]) < decisions.index(approval),
             "REJECTION_UNRESOLVED", "The current proposal was rejected after approval", entity=change["id"])
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
            Rejections(self).require_addresses("change", change_id, record["proposal_digest"], record["semantic"].get("addresses"))
            self.require_session("define", self._flow()[0], change_id=change_id)
            return {"change": change_id, "gate": stage, "scope": "structural; semantic approval is explicit"}
        self._component(record, component)
        self._approved(record)
        cancellations = [d for d in self.decisions(change_id) if d["kind"] == "change-cancel"]
        need(not any(component in d["components"] for d in cancellations), "CHANGE_CANCELED", "Canceled work requires a new change", entity=change_id)
        foundation = self.foundation(component, change_id)
        if foundation["issues"]:
            raise ModelError("FOUNDATION_INCOMPLETE", "Resolve foundation before implementation", entity=component,
                             actual=foundation["issues"])
        integrated = self.integration(change_id, component) is not None
        if not integrated:
            # An integrated component keeps its historical pins: no retroactive invalidation.
            Adrs(self).gate(record)
            self._prototype_gate(record)
            self.require_checkpoint(change_id, component, "pre-implement", record["proposal_digest"])
            self.require_gate_sessions(change_id, component, "implement",
                                       subjects=[ref["id"] for ref in foundation["references"]])
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
            verified = Verification(self).verify(change_id, component, final=stage == "integrate")
            if not integrated:
                self.require_gate_sessions(change_id, component, stage)
            if stage == "integrate" and not integrated:
                self.require_checkpoint(change_id, component, "pre-integrate", verified["candidate"]["inputs_digest"],
                                        run=verified["run_id"])
            return {**verified, "gate": stage}
        return {"change": change_id, "component": component, "gate": stage, "release": assignments[0][0]["record"]["version"]}

    def start(self, change_id, component, actor, *, sessions=()):
        result = self.gate(change_id, component, "implement")
        record, _, _ = self.change(change_id)
        decision, path = self._decision("change-start", change_id, actor, "Implementation prerequisites satisfied",
                                        proposal_digest=record["proposal_digest"], component=component,
                                        **self._cited(sessions, change_id=change_id))
        receipt = self.store.apply("change-start", {"id": change_id, "component": component,
                                   "proposal_digest": record["proposal_digest"]}, {path: encoded(decision)}, self.token)
        return {**result, "status": "in-progress", "receipt": receipt}

    def _cancelable_components(self, record):
        change_id = record["id"]
        pending = [c for c in record["semantic"]["components"] if not self.integration(change_id, c)]
        need(bool(pending), "INVALID_REFERENCE", "Integrated work requires a reversal change")
        # Preserve the legacy seeded-reader guard as well as actual integration records.
        current = self.current()["components"]
        for proposed in record["semantic"]["proposed"]:
            need(not any(current[c].get(proposed["capability_id"]) == proposed["revision"] for c in proposed["components"] if c in pending),
                 "INVALID_REFERENCE", "An integrated revision requires a new reversal change")
        return pending

    def cancel(self, change_id, actor, reason, *, sessions=()):
        record, _, _ = self.change(change_id)
        pending = self._cancelable_components(record)
        decision, path = self._decision("change-cancel", change_id, actor, reason,
                                        proposal_digest=record["proposal_digest"], components=pending,
                                        **self._cited(sessions, change_id=change_id))
        receipt = self.store.apply("change-cancel", {"id": change_id, "actor": actor, "reason": reason}, {path: encoded(decision)}, self.token)
        return {"decision": decision, "status": "canceled" if len(pending) == len(record["semantic"]["components"]) else "partially-integrated", "receipt": receipt}

    def inspect_change(self, change_id, *, deep=True, include_findings=True, include_flow=True):
        from .verification import Verification
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
        rejections = Rejections(self)
        rejection_state = rejections.state("change", change_id, record["proposal_digest"], approved=valid, decisions=decisions)
        if rejection_state in {"rejected", "revised"} and status not in {"integrated", "partially-integrated", "canceled"}:
            status = rejection_state
        valid = valid and rejection_state not in {"rejected", "withdrawn"}
        result = {"change": record, "status": status, "components": progress, "approval": approval,
                  "rejections": rejections.history("change", change_id, value=record["semantic"].get("addresses"),
                                                   pin=record["proposal_digest"], decisions=decisions),
                  "approval_current": valid, "decisions": decisions, "issues": issues,
                  "origins": record["semantic"].get("origins", []),
                  "coverage": record["semantic"].get("coverage", {"criteria": [], "derived": []}),
                  "architecture_decisions": Adrs(self).declared(record),
                  "integrations": {c: r for c, r in integrated.items() if r},
                  "review_policy": Verification(self).policy(change_id)}
        if include_findings:
            result["findings"] = []
            try:
                result["findings"] = [row for component in sorted(progress)
                                      for row in Verification(self).findings(change_id, component)]
            except ModelError as exc:
                result["issues"].append(exc.issue)
        if include_flow:
            result["flow"] = self._conformance(record, decisions, approval, valid, rejection_state)
        return result

    # Section 7.6: per-stage conformance. Read-only and deterministic: it reads records only, never
    # executes checks, queries Git or remotes, or writes. Any unreadable record becomes a blocked
    # entry carrying its issue, and a missing or invalid flow is reported as {"error": issue}.

    @staticmethod
    def _entry(status, record=None, actor=None, criteria=(), **extra):
        return {"status": status, "record": record, "actor": actor, "criteria": list(criteria), **extra}

    @staticmethod
    def _point(checkpoint, texts):
        """What a pending human point presents: its decider and each criterion with its text."""
        return {"decider": checkpoint["decider"],
                "criteria": [{"id": cid, "text": texts[cid]} for cid in checkpoint["criteria"]]}

    def _decided(self, status, decision, **extra):
        return self._entry(status, decision["id"], decision["actor"], decision.get("criteria", []), **extra)

    def _hook_entry(self, chain, hook, point, pin, texts, *, integrated):
        """Non-raising state of one declared hook on one component; mirrors require_checkpoint."""
        base = {"name": hook, "subject": pin}
        if pin is not None:
            rows = [d for d in chain if d["subject"]["digest"] == pin]
            revise = [i for i, d in enumerate(chain) if d["outcome"] == "rejected" and d["consequence"] == "revise"]
            if rows and rows[-1]["outcome"] == "approved" and chain.index(rows[-1]) > max(revise, default=-1):
                return self._decided("done", rows[-1], **base)
            latest = chain[-1] if chain else None
            if latest and latest["outcome"] == "rejected" and (latest["subject"]["digest"] == pin
                                                              or latest["consequence"] == "cancel"):
                return self._decided("blocked", latest, consequence=latest["consequence"], **base)
        if integrated and hook != "handoff":
            # The gates skip these hooks once a component is integrated (no retroactive invalidation).
            return self._entry("n/a", **base)
        return self._entry("pending", pending=self._point(point, texts), **base)

    def _conformance(self, record, decisions, approval, approval_current, rejection_state):
        try:
            parsed, raw = self._flow()
        except ModelError as exc:
            return {"error": exc.issue}
        from .causality import one_head, scoped_heads
        from .findings import OPEN, SEVERITIES
        from .verification import Verification
        verifier = Verification(self)
        change_id, pin = record["id"], record["proposal_digest"]
        components = sorted(record["semantic"]["components"])
        texts = parsed["criteria"]
        agreement = []
        for component in components:
            try:
                self.agreed_flow(component)
            except ModelError as exc:
                if exc.issue not in agreement:
                    agreement.append(exc.issue)
        current_approval = approval is not None and approval["proposal_digest"] == pin
        canceled = {c: d["id"] for d in decisions if d["kind"] == "change-cancel" for c in d["components"]}
        by_id = {d["id"]: d for d in self.decisions()}
        stage_rows = defaultdict(list)
        for d in decisions:
            if d["entity"] == change_id and is_stage(d):
                stage_rows[(d["hook"], d["component"])].append(d)
        integrations, latest_runs = {}, {}
        for component in components:
            try:
                integrations[component] = self.integration(change_id, component)
            except ModelError:
                integrations[component] = None  # Reported by the integrate stage.
        # TL.3: the agent sessions behind each stage. Unreadable session records are reported once.
        session_issues = []
        try:
            sessions = verifier.sessions()
        except ModelError as exc:
            sessions, session_issues = [], [exc.issue]
        try:
            references = self.references()
        except ModelError:
            references = {}  # Reported by the foundation stage.

        def stage_sessions(name, component=None):
            if name == "foundation":
                subjects = {ref_id for ref_id, ref in references.items() if component in ref["components"]}
                return [s["id"] for s in sessions if s["stage"] == name and s.get("subject") in subjects]
            if name == "release":
                versions = {(r["record"]["component"], r["record"]["version"]) for r in self.releases()
                            if r["record"]["component"] == component
                            and any(m["change_id"] == change_id for m in r["record"]["changes"])}
                return [s["id"] for s in sessions if s["stage"] == name
                        and (s["release"]["component"], s["release"]["version"]) in versions]
            return [s["id"] for s in sessions if s["stage"] == name and s.get("change_id") == change_id
                    and (component is None or s.get("component") in (None, component))]

        def guarded(build, component, name):
            try:
                entry = build(component)
            except ModelError as exc:
                entry = self._entry("blocked", issue=exc.issue)
            else:
                entry = withdrawn(entry, component)
            try:
                return {**entry, "sessions": stage_sessions(name, component)}
            except ModelError:
                return {**entry, "sessions": []}  # An unreadable release is already reported by its stage.

        def withdrawn(entry, component):
            # A canceled component never proceeds: what it still awaited is blocked, not pending.
            if component not in canceled or entry["status"] != "pending":
                return entry
            return {**{k: v for k, v in entry.items() if k != "pending"}, "status": "blocked",
                    "canceled": canceled[component]}

        def hook_entry(stage, component, subject):
            hook = STAGE_HOOKS[stage]
            point = project_flow.point(parsed, hook)
            if point is None:
                return {}
            entry = self._hook_entry(stage_rows[(hook, component)], hook, point, subject, texts,
                                     integrated=integrations[component] is not None)
            return {"hook": withdrawn(entry, component)}

        def effective(component):
            integration = integrations[component]
            return integration["proposal_digest"] if integration else pin

        def foundation(component):
            # Summarized: which references are agreed on their current bytes and what is still missing.
            # The record is the agreement of the process reference, i.e. of the flow itself.
            view = self.foundation(component)
            extra = {"agreed": sorted(r["id"] for r in view["references"]), "issues": view["issues"]}
            if view["issues"]:
                extra["pending"] = self._point(project_flow.point(parsed, "foundation"), texts)
            status = "pending" if view["issues"] else "done"
            process = next((r for r in view["references"] if r["role"] == "process"), None)
            if process is None:
                return self._entry(status, **extra)
            return self._decided(status, by_id[process["decision_id"]], **extra)

        def design(component):
            if not self.profile.components[component]["user_facing"]:
                return self._entry("n/a")
            cited = record["semantic"].get("prototypes", [])
            if not cited:
                return self._entry("n/a", prototypes=[])
            rows, states = [], []
            for entry in cited:
                view = self.inspect_prototype(entry["path"])
                checkpoint = view["checkpoint"]
                state = view["state"] if view["sha256"] == entry["sha256"] else "changed"
                states.append(state)
                rows.append({"path": entry["path"], "sha256": entry["sha256"], "state": state,
                             "checkpoint": checkpoint["id"] if checkpoint else None,
                             "actor": checkpoint["actor"] if checkpoint else None,
                             "criteria": checkpoint.get("criteria", []) if checkpoint else []})
            if all(state == "approved" for state in states):
                single = rows[0] if len(rows) == 1 else {"checkpoint": None, "actor": None, "criteria": []}
                return self._entry("done", single["checkpoint"], single["actor"], single["criteria"], prototypes=rows)
            if any(state in {"rejected", "withdrawn"} for state in states):
                return self._entry("blocked", prototypes=rows)
            return self._entry("pending", prototypes=rows,
                               pending=self._point(project_flow.point(parsed, "design"), texts))

        def plan(component):
            rows = [{"version": r["record"]["version"], "status": r["status"], "intent_revision": m["intent_revision"]}
                    for r in self.releases() if r["record"]["component"] == component
                    for m in r["record"]["changes"] if m["change_id"] == change_id]
            matching = [row for row in rows if row["intent_revision"] == effective(component)]
            status = "done" if len(matching) == 1 else "blocked" if matching else "pending"
            return self._entry(status, f"{component}/{matching[0]['version']}" if len(matching) == 1 else None,
                               releases=rows)

        def implement(component):
            digest_ = effective(component)
            starts = [d for d in decisions if d["kind"] == "change-start" and d["component"] == component
                      and d["proposal_digest"] == digest_]
            runs = [a["id"] for a in verifier.attempts(change_id, component)
                    if a["candidate"]["inputs"]["proposal_digest"] == digest_]
            hook = hook_entry("implement", component, digest_)
            if starts:
                return self._entry("done", starts[-1]["id"], starts[-1]["actor"], start=starts[-1]["id"], **hook)
            if runs or integrations[component]:
                # Starting is optional: a recorded run of this revision shows the work was implemented.
                return self._entry("done", runs[0] if runs else None, start=None, **hook)
            return self._entry("pending", start=None, **hook)

        def verify(component):
            integration = integrations[component]
            if integration:
                latest_runs[component] = (integration["run_id"], "pass", integration["candidate"]["inputs_digest"])
                return self._entry("done", integration["run_id"], run_status="pass")
            attempts = verifier.attempts(change_id, component)
            if not attempts:
                return self._entry("pending", run_status=None)
            head = one_head(verifier.run_heads(attempts), "run")
            if not self.store.path(f".roclec/runs/{head['id']}/manifest.json").is_file():
                return self._entry("pending", head["id"], run_status="unfinished")
            run = verifier.read_run(head["id"])
            current = run["candidate"]["inputs"]["proposal_digest"] == pin
            latest_runs[component] = (run["id"], run["status"], run["candidate"]["inputs_digest"]) if current else None
            status = "pending" if not current else "done" if run["status"] == "pass" else "blocked"
            return self._entry(status, run["id"], run_status=run["status"], current=current)

        def review(component):
            policy = verifier.policy(change_id)
            reports = verifier.evidence(change_id, component)
            reviews = [{"id": r["id"], "actor": r["actor"], "role": r.get("role"), "outcome": r["outcome"],
                        "run": r["run_id"], "candidate": r["candidate_digest"]}
                       for r in reports if r["kind"] == "independent-review"]
            findings = verifier.findings(change_id, component)
            material = [row["key"] for row in findings if row["status"] in OPEN
                        and SEVERITIES.index(row["severity"]) >= SEVERITIES.index(self.profile.material_severity)]
            extra = {"policy": policy["id"], "enabled": policy["enabled"], "reviews": reviews,
                     "open_findings": [row["key"] for row in findings if row["status"] in OPEN]}
            if not policy["enabled"]:
                return self._entry("n/a", **extra)
            integration = integrations[component]
            if integration:
                accepted = [r for r in reviews if r["id"] in integration["evidence"] and r["outcome"] == "ready"]
                return self._entry("done", accepted[-1]["id"] if accepted else None,
                                   accepted[-1]["actor"] if accepted else None, **extra)
            # Current reviews: the head of each reviewer scope that cites the latest run's candidate.
            latest = latest_runs.get(component)
            heads = {r["id"] for scope, rows in scoped_heads(reports, verifier.report_scopes).items()
                     if scope[0] == "review" for r in rows}
            current = [r for r in reviews if latest and r["candidate"] == latest[2] and r["id"] in heads]
            if material or any(r["outcome"] != "ready" for r in current):
                return self._entry("blocked", **extra)
            if current:
                return self._entry("done", current[-1]["id"], current[-1]["actor"], **extra)
            return self._entry("pending", **extra)

        def integrate(component):
            integration = integrations[component]
            if integration is None:
                self.integration(change_id, component)  # Surfaces an unreadable record as blocked.
                latest = latest_runs.get(component)
                subject = latest[2] if latest and latest[1] == "pass" else None
                return self._entry("pending", **hook_entry("integrate", component, subject))
            return self._entry("done", integration["digest"], run=integration["run_id"],
                               target_commit=integration["target_commit"],
                               **hook_entry("integrate", component, integration["candidate"]["inputs_digest"]))

        def release(component):
            integration = integrations[component]
            rows = []
            for r in self.releases():
                if r["record"]["component"] != component or not any(m["change_id"] == change_id for m in r["record"]["changes"]):
                    continue
                publication = r["publication"]
                rows.append({"version": r["record"]["version"], "status": r["status"],
                             "publication": {"tag": publication["tag"], "commit": publication["commit"]} if publication else None})
            published = [row for row in rows if row["publication"]]
            hook = hook_entry("release", component, integration["digest"] if integration else None)
            if published:
                return self._entry("done", f"{component}/{published[0]['version']}", releases=rows, **hook)
            return self._entry("pending", releases=rows, **hook)

        builders = {"foundation": foundation, "design": design, "plan": plan, "implement": implement,
                    "verify": verify, "review": review, "integrate": integrate, "release": release}
        stages = []
        for row in parsed["stages"]:
            name = row["name"]
            stage = {"stage": name, "ai": row["ai"], "role": row["role"]}
            if not row["ai"]:
                stage.update(reason=row["reason"], limitation=HUMAN_STAGE_LIMITATION)
            checkpoint = row.get("checkpoint")
            stage["checkpoint"] = {**checkpoint, "hook": STAGE_HOOKS.get(name)} if checkpoint else None
            if name == "define":
                stage["change"] = self._entry("done", pin, sealed=True)
                stage["change"]["sessions"] = stage_sessions(name)
            elif name == "approve":
                if approval_current:
                    stage["change"] = self._decided("done", approval, flow=approval.get("flow"))
                else:
                    rejected = [d for d in decisions if d["kind"] == "rejection" and d["subject"]["type"] == "change"]
                    if rejection_state in {"rejected", "withdrawn"} and rejected:
                        stage["change"] = self._decided("blocked", rejected[-1], consequence=rejected[-1]["consequence"])
                    elif canceled and set(components) <= canceled.keys():
                        stage["change"] = self._entry("blocked", canceled=canceled[components[0]])
                    else:
                        stage["change"] = self._entry("pending", pending=self._point(checkpoint, texts))
                stage["change"]["sessions"] = stage_sessions(name)
            else:
                stage["components"] = {c: guarded(builders[name], c, name) for c in components}
            stages.append(stage)
        result = {"sha256": sha(raw), "agreed": not agreement, "agreement_issues": agreement,
                  "approved_under": approval.get("flow") if current_approval else None, "stages": stages}
        if session_issues:
            result["session_issues"] = session_issues
        return result

    def list_records(self, category, *, origin=None, open_only=False):
        need(origin is None or (category == "changes" and text(origin)), "INVALID_INPUT",
             "Origin filtering requires a change list and an origin ID", exit_code=2)
        need(not open_only or category == "rejections", "INVALID_INPUT", "--open requires rejections", exit_code=2)
        if category == "rejections":
            return self._list_rejections(open_only=open_only)
        if category == "releases":
            return [{"component": item["record"]["component"], "version": item["record"]["version"],
                     "status": item["status"]} for item in self.releases()]
        if category == "changes":
            items = (self.inspect_change(path.parent.name, include_findings=False, include_flow=False)
                     for path in sorted(self.store.path(".roclec/changes").glob("*/change.json")))
            return [{"id": item["change"]["id"], "status": item["status"], "components": item["components"],
                     "approval_current": item["approval_current"]}
                    for item in items if origin is None or any(o["id"] == origin for o in item["origins"])]
        if category == "adrs":
            return Adrs(self).list()
        if category == "futs":
            views = (self.inspect_fut(path.stem) for path in sorted(self.store.path(".roclec/futs").glob("*.json")))
            return [{"id": view["fut"]["id"], "scope": view["scope"], "status": view["status"]} for view in views]
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
        fields(record, ("model_schema", "id", "source", "finding", "impact", "questions"), ("scope",))
        schema(record)
        identifier(record["id"], "FUT")
        # TL.5: a FUT without scope is a product FUT; old records are never rewritten.
        need(record.get("scope", "product") in FUT_SCOPES, "INVALID_INPUT", "Unknown FUT scope", exit_code=2,
             expected=list(FUT_SCOPES), actual=record.get("scope"),
             remediation="Use scope product (behavior to build) or process (friction in the project flow), or omit it.")
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
        every = self.decisions()
        decisions = [d for d in every if d["entity"] == fut_id and d["kind"] == "fut-decide"]
        # Friction -> flow adjustment -> reason: the process agreements that cite this FUT.
        addressed = [{"decision": d["id"], "flow": d["sources"][d["entity"]], "reason": d["reason"], "actor": d["actor"]}
                     for d in every if d["kind"] == "foundation" and fut_id in d.get("futs", [])]
        return {"fut": record, "scope": record.get("scope", "product"),
                "status": decisions[-1]["outcome"] if decisions else "captured", "decisions": decisions,
                "addressed_by": addressed}

    def decide_fut(self, fut_id, outcome, actor, reason, target=None, *, sessions=()):
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
                ref = self.references().get(decision.get("entity"))
                process = "futs" in decision or (ref is not None and ref["role"] == "process")
                if current["scope"] == "process":
                    need(fut_id in decision.get("futs", []), "INVALID_REFERENCE",
                         "A process FUT is promoted only to the flow agreement that cites it", exit_code=2, entity=target,
                         remediation=f"Agree the flow citing it (foundation agree --ref REF --fut {fut_id} ...) and "
                                     "promote the FUT to that decision.")
                else:
                    need(not process, "INVALID_REFERENCE", "A product FUT cannot be promoted to a process agreement",
                         exit_code=2, entity=target,
                         remediation="Promote a product FUT to a change, capability or requirement, or capture the "
                                     "friction as a process FUT.")
        need(current["status"] in {"captured", "evaluating"} or outcome == "evaluating", "INVALID_REFERENCE",
             "Reopen a resolved FUT with an explicit evaluating decision")
        decision, path = self._decision("fut-decide", fut_id, actor, reason, outcome=outcome, target=target,
                                        **self._cited(sessions))
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
                integration = self.integration(member["change_id"], component)
                if integration is not None and self._handoff_deferred(member["change_id"], component, integration, decisions):
                    continue  # The user deferred this member at handoff; it may leave the planning release.
                need(integration is None, "CHANGE_IN_PROGRESS", "An integrated release member cannot be removed",
                     entity=member["change_id"],
                     remediation="Only a deferred handoff rejection (checkpoint --hook handoff --outcome rejected "
                                 "--consequence defer --fut FUT-NNN) lets integrated work leave a planning release.")
                started = any(d["kind"] == "change-start" and d["component"] == component
                              and d["proposal_digest"] == member["intent_revision"] for d in decisions)
                from .verification import Verification
                started = started or any(r["change_id"] == member["change_id"] and r["component"] == component
                                         for r in (Verification(self).read_run(p.parent.name) for p in self.store.path(".roclec/runs").glob("RUN-*/manifest.json")))
                canceled = any(d["kind"] == "change-cancel" and component in d["components"] for d in decisions)
                replacement = any(m["change_id"] == member["change_id"] for m in members)
                need(not started or canceled or replacement, "CHANGE_IN_PROGRESS",
                     "Cancel pending work before removing assignment, or bind its newly approved revision explicitly")
        payload = {"component": component, "version": version, "record": record}
        if same:
            receipts = self.store.path(".roclec/receipts")
            names = sorted(p.name for p in receipts.glob("*.json")) if receipts.is_dir() else []
            target = f".roclec/releases/{component}/{version}/release.json"
            reused = None
            if same[0]["record"] == record:
                # An unchanged repeat replays the receipt that wrote the current bytes, so it stays idempotent.
                current = sha(self.store.path(target).read_bytes())  # Actual bytes: a reformatted file must not replay.
                for name in names:
                    previous = read_json(receipts / name)
                    if (isinstance(previous, dict) and previous.get("kind") == "release-plan"
                            and isinstance(previous.get("payload"), dict)
                            and previous["payload"].get("component") == component
                            and previous["payload"].get("version") == version
                            and previous["payload"].get("record") == record
                            and previous.get("writes", {}).get(target) == current):
                        reused = previous["payload"]
                        break
            if reused is not None:
                payload = reused
            else:
                # A re-plan may restore an earlier membership byte for byte (e.g. after a deferred handoff);
                # without a fresh generation the store would refuse to replay that earlier, diverged receipt.
                payload["generation"] = digest({"inputs": self.token, "receipts": names})
        receipt = self.store.apply("release-plan", payload,
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
        Rejections(self).check()
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
        session_records = []
        for path in sorted(self.store.path(".roclec/evidence").glob("EVD-*.json")):
            report = verifier.read_evidence(path, runs)
            if report["kind"] == "agent-session":
                session_records.append(report)
                warnings.extend(verifier.session_issues(report))
                continue
            reports[scope(report)].append(report)
        from .sessions import policy_warnings, stray_warnings
        warnings.extend(stray_warnings(self.store, session_records))
        warnings.extend(policy_warnings(self.profile, session_records))
        from .findings import project as project_findings
        for records in reports.values():
            scoped_heads(records, verifier.report_scopes)
            project_findings(records)
        for path in self.store.path(".roclec/integrations").glob("*/*/*.json"):
            self.integration(path.parent.parent.name, path.parent.name, path.stem)
        from .releases import Releases
        for path in self.store.path(".roclec/releases").glob("*/*/preparations/*.json"):
            Releases(self).preparation(path.parent.parent.parent.name, path.parent.parent.name, path.stem)
        warnings.extend(self._flow_warnings())
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
                        "target_ref", "target_commit"), ("baseline_release", "finding_state"))
        need(text(record["target_ref"]) and record["target_ref"].startswith("refs/remotes/")
             and text(record["target_commit"]) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", record["target_commit"]),
             "INVALID_REFERENCE", "Integration requires a frozen target tracking ref and commit")
        need(record.get("change_id") == change_id and record.get("component") == component
             and record.get("proposal_digest") == proposal_digest
             and record.get("digest") == digest({k: v for k, v in record.items() if k != "digest"}),
             "HASH_MISMATCH", "Integration record integrity mismatch")
        identifier(record["run_id"], "RUN")
        if "finding_state" in record:
            fingerprint(record["finding_state"])
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

    def _flow_view(self, *, learning=False):
        """Return (flow, view path, existing bytes, status, learning), or None when the flow file is missing.

        Status and learning are computed only with `learning`: the status compares the full view,
        whose learning section is projected from records (TL.6). Without it both are None (a caller
        that needs only the view path reads no records).
        """
        try:
            flow, _ = self._flow()
        except ModelError as exc:
            if exc.issue["code"] == "FLOW_MISSING":
                return None
            raise
        relative = flow["view"]
        path = self.store.path(relative)
        existing = path.read_bytes() if path.is_file() else None
        if not learning:
            return flow, relative, existing, None, None
        data = self._flow_learning()
        status = "edited" if path.exists() and existing is None else \
            project_flow.view_status(flow, self.profile.data, existing, data)
        return flow, relative, existing, status, data

    def _flow_learning(self):
        """Records projected for the flow view's learning section (TL.6): counts and lists, no judgments.

        Read-only. Every record is read through its usual validation, so unreadable records fail with
        their usual errors. FUTs cited by an agreement but absent stay listed without their finding.
        """
        from .findings import project as project_findings
        from .verification import Verification
        decisions = self.decisions()
        futs = {}
        for path in sorted(self.store.path(".roclec/futs").glob("*.json")):
            identifier(path.stem, "FUT")
            record = self._fut_record(self.read(path.relative_to(self.profile.root).as_posix()))
            need(record["id"] == path.stem, "INVALID_REFERENCE", "FUT identity mismatch", entity=path.stem)
            outcomes = [d["outcome"] for d in decisions if d["entity"] == path.stem and d["kind"] == "fut-decide"]
            futs[path.stem] = {"scope": record.get("scope", "product"), "finding": record["finding"],
                               "status": outcomes[-1] if outcomes else "captured"}
        process = [ref["id"] for ref in self.references().values() if ref["role"] == "process"]
        revisions, cited = [], set()
        for decision in decisions:
            if decision["kind"] != "foundation" or decision["entity"] not in process:
                continue
            cited.update(decision.get("futs", []))
            revisions.append({"decision": decision["id"], "flow": decision["sources"][decision["entity"]],
                              "actor": decision["actor"], "reason": decision["reason"],
                              "futs": [{"id": fut_id, "scope": futs.get(fut_id, {}).get("scope"),
                                        "finding": futs.get(fut_id, {}).get("finding")}
                                       for fut_id in decision.get("futs", [])]})
        open_futs = [{"id": fut_id, "status": row["status"], "finding": row["finding"]} for fut_id, row in sorted(futs.items())
                     if row["scope"] == "process" and row["status"] in {"captured", "evaluating"} and fut_id not in cited]
        rejections = []
        for row in self._list_rejections():
            kind = row["subject"]["type"]
            stage = project_flow.SUBJECT_POINTS.get(kind) or project_flow.HOOKS[row["hook"]]
            subject, entity = (kind, row["entity"]) if kind != "stage" else \
                (f"stage {row['hook']}", f"{row['entity']}/{row['component']}")
            rejections.append({"stage": stage, "subject": subject, "entity": entity, "consequence": row["consequence"],
                               "open": row["open"], "decision": row["id"]})
        verifier = Verification(self)
        runs = {p.parent.name: verifier.read_run(p.parent.name) for p in self.store.path(".roclec/runs").glob("RUN-*/manifest.json")}
        groups, sessions, findings = defaultdict(list), defaultdict(int), defaultdict(int)
        for path in sorted(self.store.path(".roclec/evidence").glob("EVD-*.json")):
            record = verifier.read_evidence(path, runs)
            if record["kind"] == agent_sessions.KIND:
                sessions[(record["role"], record["stage"])] += 1
                continue
            groups[(record["change_id"], record["component"], (record.get("release") or {}).get("version"))].append(record)
        for key in sorted(groups, key=lambda k: tuple("" if v is None else v for v in k)):
            for row in project_findings(groups[key]):
                findings[(row["severity"], row["status"])] += 1
        return {"revisions": revisions, "open_futs": open_futs, "rejections": rejections,
                "findings": [{"severity": s, "status": t, "count": n} for (s, t), n in sorted(findings.items())],
                "sessions": [{"role": r, "stage": t, "count": n} for (r, t), n in sorted(sessions.items())]}

    def _flow_warnings(self):
        def warning(code, message, remediation, **context):
            return {**ModelError(code, message, remediation=remediation, **context).issue, "severity": "warning"}
        view = self._flow_view(learning=True)
        if view is None:
            components = " ".join(f"--component {c}" for c in sorted(self.profile.components))
            return [warning("FLOW_MISSING", f"{project_flow.FLOW_PATH} does not exist",
                            f"Run `roclec skills` to seed the default flow, then `roclec reference add flow --path "
                            f"{project_flow.FLOW_PATH} --role process {components}` and `roclec foundation agree --ref flow`.",
                            path=project_flow.FLOW_PATH, entity="flow")]
        flow, relative, _, status, _ = view
        result = list(flow["warnings"])
        if status in {"stale", "missing"}:
            result.append(warning("FLOW_VIEW_STALE", f"Generated flow view is {status}", "Run `roclec views --write`.",
                                  path=relative, entity="flow", actual=status))
        elif status == "edited":
            result.append(warning("FLOW_VIEW_EDITED", "Generated flow view has local edits or is not a Roclec view",
                                  f"Move the edits into {project_flow.FLOW_PATH}, delete {relative} and run `roclec views --write`.",
                                  path=relative, entity="flow"))
        return result

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
        payload, observed = {"sources": current}, {}
        flow_view = self._flow_view(learning=True)  # Skipped when the flow file is missing; `check` warns.
        if flow_view is not None:
            flow, relative, existing, status, learning = flow_view
            need(status != "edited", "UNMANAGED_FILE", "Flow view is unmanaged or has local edits; resolve them before regenerating",
                 path=relative, remediation=f"Move the edits into {project_flow.FLOW_PATH}, delete {relative} and retry.")
            if status != "current":
                stale.append(relative)
                writes[relative] = project_flow.render(flow, self.profile.data, learning)
                payload["flow_view"] = relative
                # Restoring a deleted or edited view repeats earlier bytes; without a fresh
                # generation the store would refuse to replay the diverged earlier receipt.
                receipts = self.store.path(".roclec/receipts")
                payload["generation"] = digest({"inputs": self.token, "receipts": sorted(
                    p.name for p in receipts.glob("*.json")) if receipts.is_dir() else []})
                observed[relative] = existing
        count = len(caps) + (flow_view is not None)
        if writes and write:
            # The flow view is outside the store token; recheck its bytes under the lock.
            def unchanged():
                need(all((self.store.path(p).read_bytes() if self.store.path(p).is_file() else None) == b
                         for p, b in observed.items()), "BASE_CONFLICT", "Project inputs changed during validation", exit_code=3)
            receipt = self.store.apply("views", payload, writes, self.token, validate=unchanged)
            return {"views": count, "written": sorted(writes), "receipt": receipt}
        need(not stale, "VIEW_STALE", "Generated views need regeneration", actual=stale,
             remediation="views --write")
        return {"views": count, "written": []}
