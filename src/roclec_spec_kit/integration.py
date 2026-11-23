"""Reconstructed, preconditioned integration plans; no arbitrary write imports."""
from __future__ import annotations

import os
from pathlib import Path

from .model import digest, encoded, fields, need, read_json, schema, sha
from .verification import Verification, git


def target_tip(repo, ref):
    result = git(repo, "show-ref", "--verify", "--hash", ref, check=False)
    return result.stdout.decode("ascii").strip() if result.returncode == 0 else None


def export_plan(kernel, plan, out):
    out = Path(out).absolute()
    need(not out.is_symlink(), "INVALID_PATH", "Plan output cannot be a symlink", exit_code=2)
    out = out.parent.resolve() / out.name
    need(not out.is_relative_to(kernel.profile.root / ".roclec") and not out.is_relative_to(kernel.profile.root / "specs/capabilities"),
         "UNMANAGED_FILE", "Export a plan outside authority namespaces", path=out)
    need(not out.exists(), "UNMANAGED_FILE", "Plan output already exists", path=out)
    need(out.parent.is_dir(), "INVALID_PATH", "Plan output needs an existing directory", exit_code=2)
    with out.open("xb") as stream:
        stream.write(encoded(plan))
        stream.flush()
        os.fsync(stream.fileno())
    return {"plan": plan, "out": str(out)}


class Integration:
    def __init__(self, kernel):
        self.k = kernel
        self.v = Verification(kernel)

    def build(self, change_id, component, run_id):
        need(self.k.integration(change_id, component) is None,
             "OPERATION_CONFLICT", "This change component is already integrated", exit_code=3)
        self.k.gate(change_id, component, "implement")
        record, files, _ = self.k.change(change_id, check_base=True, check_component=component)
        self.k.preserve_integrated(record)
        verified = self.v.verify(change_id, component, run_id=run_id, final=True)
        # A declared pre-integrate hook needs a human approval of exactly this run's candidate.
        self.k.require_checkpoint(change_id, component, "pre-integrate", verified["candidate"]["inputs_digest"], run=run_id)
        # A required implement, verify or review stage needs its agent session (the integrate gate, TL.4).
        self.k.require_gate_sessions(change_id, component, "integrate", kind=record["kind"])
        repo = self.k.profile.repo(component)
        target_ref = self.k.profile.components[component]["target_ref"]
        target_commit = target_tip(repo, target_ref)
        need(target_commit, "INVALID_REFERENCE", "Target tracking ref is missing", entity=component, actual=target_ref,
             remediation="Fetch the target ref before preparing integration.")
        need(git(repo, "merge-base", "--is-ancestor", verified["candidate"]["head"], target_commit, check=False).returncode == 0,
             "TARGET_NOT_INTEGRATED", "The candidate commit does not belong to the target history", entity=component)
        destination_tip = {"target_ref": target_ref, "target_commit": target_commit}
        current = self.k.current()
        writes = {}
        for entry in record["semantic"]["proposed"]:
            if component not in entry["components"]:
                continue
            cap, revision = entry["capability_id"], entry["revision"]
            prefix = f"proposed/{cap}/{revision}/"
            for relative, content in files.items():
                if relative.startswith(prefix):
                    destination = f".roclec/contracts/{cap}/{revision}/{relative[len(prefix):]}"
                    path = self.k.store.path(destination)
                    need(not path.exists() or path.read_bytes() == content, "HASH_MISMATCH", "Immutable contract destination diverged", path=destination)
                    writes[destination] = content
            current["components"][component][cap] = revision
        integration = {"model_schema": 2, "change_id": change_id, "component": component,
                       "proposal_digest": record["proposal_digest"], "run_id": run_id,
                       "candidate": verified["candidate"], "evidence": verified["evidence"],
                       "policy_id": verified["policy_id"], "finding_state": verified["finding_state"],
                       "contracts": current["components"][component], **destination_tip}
        if "baseline_release" in record["semantic"]:
            baseline = record["semantic"]["baseline_release"]
            integration["baseline_release"] = baseline
            integration["contracts"] = self.k.release(baseline["component"], baseline["version"])["publication"]["contracts"]
        integration["digest"] = digest(integration)
        # Snapshots first, then exactly one index replacement, then the record.
        writes[".roclec/current.json"] = encoded(current)
        writes[f".roclec/integrations/{change_id}/{component}/{record['proposal_digest']}.json"] = encoded(integration)
        plan = {"model_schema": 2, "kind": "integrate", "target": {"change_id": change_id, "component": component},
                "expected": {"store_token": self.k.token, "bases": record["semantic"]["bases"]},
                "inputs": {"run_id": run_id, "proposal_digest": record["proposal_digest"], "candidate": verified["candidate"],
                           **destination_tip},
                "writes": {p: sha(b) for p, b in writes.items()}, "gate_result": {"ok": True, "gate": "integrate"}}
        plan["operation_id"] = digest(plan)
        return plan, writes

    def prepare(self, change_id, component, run_id, out):
        plan, _ = self.build(change_id, component, run_id)
        return export_plan(self.k, plan, out)

    def apply(self, file):
        self.k.store.guard_branch("apply")
        plan = read_json(file)
        fields(plan, ("model_schema", "operation_id", "kind", "target", "expected", "inputs", "writes", "gate_result"))
        schema(plan)
        need(plan["kind"] in {"integrate", "release-prepare", "release-record"}, "OPERATION_CONFLICT", "Unsupported plan kind", exit_code=3)
        need(plan["operation_id"] == digest({k: v for k, v in plan.items() if k != "operation_id"}),
             "OPERATION_CONFLICT", "Plan integrity mismatch", exit_code=3)
        receipt_path = self.k.store.path(f".roclec/receipts/{plan['operation_id']}.json")
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            need(receipt.get("operation_id") == plan["operation_id"] and receipt.get("kind") == plan["kind"]
                 and receipt.get("writes") == plan["writes"], "OPERATION_CONFLICT", "Receipt does not match this plan", exit_code=3)
            # Returning a historical receipt does not replay writes or roll back a later index.
            return {"receipt": receipt, "already_applied": True}
        if plan["kind"] != "integrate":
            from .releases import Releases
            return Releases(self.k).apply(plan)
        target = plan["target"]
        fields(target, ("change_id", "component"))
        destination = {key: plan["inputs"].get(key) for key in ("target_ref", "target_commit")}
        component = target["component"]
        repo = self.k.profile.repo(component)
        ref = self.k.profile.components[component]["target_ref"]
        need(destination["target_ref"] == ref and destination["target_commit"] is not None
             and target_tip(repo, ref) == destination["target_commit"],
             "BASE_CONFLICT", "Target ref moved after integration preparation", exit_code=3,
             remediation="Fetch and prepare a new integration plan.")
        record, _, _ = self.k.change(target["change_id"], check_base=True, check_component=target["component"])
        need(plan["expected"]["store_token"] == self.k.token, "BASE_CONFLICT", "Project changed after preparation", exit_code=3)
        rebuilt, writes = self.build(target["change_id"], target["component"], plan["inputs"]["run_id"])
        need(rebuilt == plan, "OPERATION_CONFLICT", "Plan differs from canonical reconstruction", exit_code=3)
        candidate = plan["inputs"]["candidate"]

        def validate():
            need(target_tip(repo, ref) == destination["target_commit"],
                 "BASE_CONFLICT", "Target ref moved before integration", exit_code=3)
            now = self.v.candidate(target["change_id"], target["component"], candidate["base"], final=True)
            need(now == candidate, "BASE_CONFLICT", "Code candidate changed before application", exit_code=3)

        payload = {**target, "proposal_digest": record["proposal_digest"], "candidate": candidate, **destination}
        receipt = self.k.store.apply("integrate", payload, writes, self.k.token, validate=validate, plan=plan)
        need(receipt.get("status") != "rolled-back", "BASE_CONFLICT",
             "Target ref changed before confirmation and integration was rolled back", exit_code=3)
        return {"receipt": receipt, "integrated": target}
