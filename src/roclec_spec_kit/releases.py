"""C3 release eligibility and read-only Git publication verification.

Plans are reconstructed from immutable inputs. Only operation apply persists
preparations/publications; this module never creates tags, pushes or deploys.
"""
from __future__ import annotations

import subprocess

from .model import (ModelError, digest, encoded, fields, fingerprint, identifier, need,
                    read_json, sha, strings, text, version_key)
from .verification import Verification, git


class Releases:
    def __init__(self, kernel):
        self.k, self.store = kernel, kernel.store

    def context(self, component, version, *, unpublished=False):
        version_key(version)
        release = self.k.release(component, version)
        record = release["record"]
        need(not unpublished or release["publication"] is None, "VERSION_INVALID", "Published releases are immutable")
        need(bool(record["changes"]), "RELEASE_UNASSIGNED", "A release needs approved integrated members")
        baselines, changes = [], []
        for member in record["changes"]:
            integration = self.k.integration(member["change_id"], component, member["intent_revision"])
            need(integration is not None, "INVALID_REFERENCE", "Release member is not integrated at its approved revision", entity=member["change_id"])
            folder = self.store.path(f".roclec/changes/{member['change_id']}/revisions/{member['intent_revision']}")
            change, _, _ = self.k.change(member["change_id"], source=folder, historical=True)
            changes.append(change)
            for dep in change["semantic"]["dependencies"]:
                satisfied = (self.k.release(dep["component"], dep["release"])["publication"] is not None if "release" in dep
                             else self.k.current()["components"][dep["component"]].get(dep["capability_id"]) == dep["revision"])
                need(satisfied, "DEPENDENCY_PENDING", "Release dependency is not satisfied", actual=dep)
            if "baseline_release" in change["semantic"]:
                baselines.append(change["semantic"]["baseline_release"])
        if baselines:
            need(len(baselines) == len(record["changes"]) and all(b == baselines[0] for b in baselines)
                 and baselines[0] == {"component": component, "version": record["base_tag"]},
                 "INVALID_REFERENCE", "Historical fixes must share the explicit release base")
            contracts = self.k.release(**baselines[0])["publication"]["contracts"]
        elif release["publication"]:
            contracts = release["publication"]["contracts"]
        else:
            published = [r["publication"] for r in self.k.releases() if r["record"]["component"] == component and r["publication"]
                         and version_key(r["record"]["version"], historical=True) < version_key(version)]
            previous = max(published, key=lambda p: version_key(p["version"], historical=True), default=None)
            contracts = dict(previous["contracts"]) if previous else {}
            pending = list(changes)
            while pending:
                progressed = False
                for change in pending[:]:
                    bases = [b for b in change["semantic"]["bases"] if b["component"] == component]
                    if not all(contracts.get(b["capability_id"]) == b["revision"] for b in bases):
                        continue
                    for proposed in change["semantic"]["proposed"]:
                        if component in proposed["components"]:
                            contracts[proposed["capability_id"]] = proposed["revision"]
                    pending.remove(change)
                    progressed = True
                need(progressed, "BASE_CONFLICT", "Release members do not form an explicit contract lineage from published history", exit_code=3,
                     actual=[c["id"] for c in pending])
        for cap, revision in contracts.items():
            self.k.contract(cap, revision)
        return {"component": component, "version": record["version"], "release_digest": digest(record), "contracts": contracts}

    def version(self, record):
        numeric = version_key(record["version"])
        published = [r for r in self.k.releases() if r["record"]["component"] == record["component"] and r["publication"]]
        if record["kind"] == "release":
            if published:
                previous = max(version_key(r["record"]["version"], historical=True) for r in published)
                need((numeric[0] > previous[0] and numeric[1:] == (0, 0)) or
                     (numeric[0] == previous[0] and numeric[1] > previous[1] and numeric[2] == 0),
                     "VERSION_INVALID", "Release no longer advances its component's published history")
        else:
            base = self.k.release(record["component"], record["base_tag"])["publication"]
            need(base is not None, "VERSION_INVALID", "Correction requires a published base")
            base_version = version_key(base["version"], historical=True)
            patches = [version_key(r["record"]["version"], historical=True)[2] for r in published
                       if version_key(r["record"]["version"], historical=True)[:2] == numeric[:2]]
            need(numeric[:2] == base_version[:2] and numeric[2] > max(patches), "VERSION_INVALID", "Correction must advance the published base line")
            need(self.resolve(record["component"], f"refs/tags/{record['base_tag']}") == base["commit"],
                 "TAG_MISMATCH", "Correction base tag differs from published history")

    def resolve(self, component, ref, *, code="TAG_MISMATCH"):
        need(text(ref) and not ref.startswith("-"), code, "Expected an explicit Git reference")
        result = git(self.k.profile.repo(component), "rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
        need(result.returncode == 0, code, "Referenced commit does not exist locally", actual=ref)
        return result.stdout.decode().strip()

    def fixes(self, record, candidate, evidence):
        repo, included = self.k.profile.repo(record["component"]), []
        for member in record["changes"]:
            folder = self.store.path(f".roclec/changes/{member['change_id']}/revisions/{member['intent_revision']}")
            change, _, _ = self.k.change(member["change_id"], source=folder, historical=True)
            if change["kind"] != "fix":
                continue
            refs = [f for f in change["semantic"].get("fixes", []) if f["component"] == record["component"]]
            need(bool(refs), "FIX_NOT_INCLUDED", "Fix needs explicit implementation commit and restored obligations", entity=change["id"])
            for fix in refs:
                original = self.resolve(record["component"], fix["commit"], code="FIX_NOT_INCLUDED")
                commit = original
                resolved_backport = None
                if fix["backport"]:
                    backport = fix["backport"]
                    commit = self.resolve(record["component"], backport["commit"], code="FIX_NOT_INCLUDED")
                    from .causality import one_head, scoped_heads
                    verifier = Verification(self.k, release={"component": record["component"], "version": record["version"]})
                    heads = scoped_heads(verifier.evidence(None, record["component"]), verifier.report_scopes)
                    observations = [one_head(heads, ("observation", ac)) for ac in fix["acceptance_ids"]]
                    report = observations[0] if observations else None
                    if (not report or not all(item == report for item in observations)
                            or backport.get("evidence_id", report["id"]) != report["id"]
                            or report["id"] not in evidence or report["outcome"] != "pass" or not report["checks"]):
                        report = None
                    need(report is not None,
                         "FIX_NOT_INCLUDED", "Backport requires current preservation evidence for its obligations")
                    resolved_backport = {"commit": commit, "evidence_id": report["id"]}
                need(git(repo, "merge-base", "--is-ancestor", commit, candidate["head"], check=False).returncode == 0,
                     "FIX_NOT_INCLUDED", "Fix implementation is not included in the candidate", actual=commit)
                included.append({"change_id": change["id"], "source_commit": original, "included_commit": commit,
                                 "backport": resolved_backport, "requirement_ids": fix["requirement_ids"], "acceptance_ids": fix["acceptance_ids"]})
        return included

    def gate(self, component, version, run_id=None):
        from .integration import target_tip
        context = self.context(component, version, unpublished=True)
        record = self.k.release(component, version)["record"]
        repo = self.k.profile.repo(component)
        ref = self.k.profile.components[component]["target_ref"]
        tip = target_tip(repo, ref)
        for member in record["changes"]:
            integration = self.k.integration(member["change_id"], component, member["intent_revision"])
            need(tip and git(repo, "merge-base", "--is-ancestor", integration["candidate"]["head"], tip, check=False).returncode == 0,
                 "TARGET_NOT_INTEGRATED", "Release member is no longer in the configured target history",
                 entity=member["change_id"], actual=ref)
        self.version(record)
        verified = Verification(self.k, release={"component": component, "version": version}).verify(None, component, run_id=run_id, final=True)
        fixes = self.fixes(record, verified["candidate"], verified["evidence"])
        return {**verified, "gate": "release", "context": context, "fixes": fixes, "limitations": self.limitations(record)}

    def limitations(self, record):
        """Non-blocking: approved members that applied an ADR superseded since then."""
        from .adr import Adrs
        adrs, result = Adrs(self.k), []
        view = adrs.view()
        for member in record["changes"]:
            folder = self.store.path(f".roclec/changes/{member['change_id']}/revisions/{member['intent_revision']}")
            change, _, _ = self.k.change(member["change_id"], source=folder, historical=True)
            result.extend(adrs.superseded_citations(change, view))
        return sorted(result, key=lambda item: (item["change_id"], item["adr"]))

    def preparation(self, component, version, preparation):
        fingerprint(preparation)
        record = self.k.read(f".roclec/releases/{component}/{version}/preparations/{preparation}.json")
        fields(record, ("model_schema", "component", "version", "release_digest", "contracts", "candidate", "run_id", "evidence", "policy_id", "fixes"))
        need(digest(record) == preparation and (record["component"], record["version"]) == (component, version),
             "HASH_MISMATCH", "Preparation differs from its immutable identity")
        candidate = record["candidate"]
        run = Verification(self.k).read_run(record["run_id"])
        need(candidate["inputs_digest"] == digest(candidate["inputs"])
             and run.get("release") == {"component": component, "version": version}
             and run["candidate"]["inputs_digest"] == candidate["inputs_digest"] and run["status"] == "pass"
             and candidate["inputs"]["release"] == {"component": component, "version": version,
                  "release_digest": record["release_digest"], "contracts": record["contracts"]},
             "INVALID_REFERENCE", "Preparation must bind its actual final release run and contracts")
        return record

    def remote(self, component, remote, tag, commit):
        repo = self.k.profile.repo(component)
        need(remote in git(repo, "remote").splitlines(), "TAG_MISMATCH", "Select a configured remote by name")
        need(tag.startswith("v") and not any(c.isspace() for c in tag), "TAG_MISMATCH", "Invalid publication tag")
        try:
            result = git(repo, "ls-remote", "--exit-code", "--tags", remote, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}", check=False)
        except subprocess.TimeoutExpired as exc:
            raise ModelError("TAG_MISMATCH", "Remote publication could not be verified") from exc
        lines = sorted(result.stdout.decode("utf-8", "replace").splitlines())
        refs = dict((line.split()[1], line.split()[0]) for line in lines if len(line.split()) == 2)
        resolved = refs.get(f"refs/tags/{tag}^{{}}", refs.get(f"refs/tags/{tag}"))
        need(result.returncode == 0 and resolved == commit, "TAG_MISMATCH", "Remote tag does not resolve to the prepared commit",
             expected=commit, actual=resolved)
        return {"remote": remote, "tag": tag, "commit": resolved, "refs": refs, "stdout_sha256": sha(result.stdout)}

    def build_prepare(self, component, version, run_id):
        gate = self.gate(component, version, run_id)
        candidate = gate["candidate"]
        record = {"model_schema": 2, "component": component, "version": version,
                  "release_digest": gate["context"]["release_digest"], "contracts": gate["context"]["contracts"],
                  "candidate": candidate, "run_id": run_id, "evidence": gate["evidence"], "policy_id": gate["policy_id"], "fixes": gate["fixes"]}
        preparation = digest(record)
        writes = {f".roclec/releases/{component}/{version}/preparations/{preparation}.json": encoded(record)}
        need(not self.store.path(next(iter(writes))).exists(), "OPERATION_CONFLICT", "Identical preparation already exists", exit_code=3)
        return self.plan("release-prepare", component, version, {"run_id": run_id, "preparation": preparation, "candidate": candidate}, writes), writes

    def build_record(self, component, version, preparation, commit, tag, remote, actor, reason):
        need(text(actor) and text(reason), "INVALID_INPUT", "Publication record needs declared actor and reason", exit_code=2)
        prepared = self.preparation(component, version, preparation)
        gate = self.gate(component, version, prepared["run_id"])
        candidate = gate["candidate"]
        need(prepared["release_digest"] == gate["context"]["release_digest"] and prepared["contracts"] == gate["context"]["contracts"]
             and candidate["inputs_digest"] == prepared["candidate"]["inputs_digest"]
             and gate["policy_id"] == prepared["policy_id"] and gate["evidence"] == prepared["evidence"] and gate["fixes"] == prepared["fixes"],
             "EVIDENCE_STALE", "Preparation no longer matches the release, candidate or review policy")
        resolved = self.resolve(component, commit)
        need(resolved == prepared["candidate"]["head"] and tag == version and self.resolve(component, f"refs/tags/{tag}") == resolved,
             "TAG_MISMATCH", "Commit/local tag must match the prepared candidate", expected=prepared["candidate"]["head"], actual=resolved)
        for release in self.k.releases():
            publication = release["publication"]
            if publication and publication["tag"] == tag and self.k.profile.repo(release["record"]["component"]) == self.k.profile.repo(component):
                need(publication["commit"] == resolved, "TAG_MISMATCH", "Components sharing a repo/tag must publish the same commit")
        query = self.remote(component, remote, tag, resolved)
        publication = {"model_schema": 2, "component": component, "version": version,
                       "release_digest": prepared["release_digest"], "contracts": prepared["contracts"], "commit": resolved,
                       "tag": tag, "remote": remote, "evidence": {"preparation": preparation, "run_id": prepared["run_id"],
                       "candidate": prepared["candidate"], "evidence_ids": prepared["evidence"], "policy_id": prepared["policy_id"],
                       "fixes": gate["fixes"], "query": query, "actor": actor, "reason": reason}}
        inputs = {"preparation": preparation, "commit": resolved, "tag": tag, "remote": remote, "actor": actor, "reason": reason,
                  "candidate": candidate, "query": query}
        writes = {f".roclec/releases/{component}/{version}/publication.json": encoded(publication)}
        return self.plan("release-record", component, version, inputs, writes), writes

    def plan(self, kind, component, version, inputs, writes):
        plan = {"model_schema": 2, "kind": kind, "target": {"component": component, "version": version},
                "expected": {"store_token": self.k.token}, "inputs": inputs, "writes": {p: sha(b) for p, b in writes.items()},
                "gate_result": {"ok": True, "gate": "release"}}
        plan["operation_id"] = digest(plan)
        return plan

    def export(self, kind, component, version, out, **inputs):
        from .integration import export_plan
        builder = self.build_prepare if kind == "release-prepare" else self.build_record
        plan, _ = builder(component, version, **inputs)
        return export_plan(self.k, plan, out)

    def apply(self, plan):
        target, inputs = plan["target"], plan["inputs"]
        fields(target, ("component", "version"))
        need(self.k.token == plan["expected"]["store_token"], "BASE_CONFLICT", "Release inputs changed after preparation", exit_code=3)
        if plan["kind"] == "release-prepare":
            rebuilt, writes = self.build_prepare(**target, run_id=inputs["run_id"])
        else:
            rebuilt, writes = self.build_record(**target, **{k: inputs[k] for k in ("preparation", "commit", "tag", "remote", "actor", "reason")})
        need(plan == rebuilt, "OPERATION_CONFLICT", "Release plan differs from canonical reconstruction", exit_code=3)
        candidate = inputs["candidate"]
        payload = {**target, "candidate": candidate, **({"query": inputs["query"]} if "query" in inputs else {})}

        def validate():
            self.recovery_guard(payload)
            need(not git(self.k.profile.repo(target["component"]), "status", "--porcelain=v1", "--untracked-files=all"),
                 "CANDIDATE_DIRTY", "Code repo changed before application")

        receipt = self.store.apply(plan["kind"], payload, writes, self.k.token, validate=validate, plan=plan)
        return {"receipt": receipt, "preparation": inputs.get("preparation")}

    def recovery_guard(self, payload):
        scope = {k: payload[k] for k in ("component", "version")}
        candidate = Verification(self.k, release=scope).candidate(None, scope["component"], payload["candidate"]["base"])
        need(candidate["inputs_digest"] == payload["candidate"]["inputs_digest"] and candidate["head"] == payload["candidate"]["head"],
             "OPERATION_CONFLICT", "Release code candidate diverged; recovery cannot proceed", exit_code=3)
        if "query" in payload:
            q = payload["query"]
            need(self.remote(scope["component"], q["remote"], q["tag"], q["commit"]) == q,
                 "OPERATION_CONFLICT", "Remote publication changed during operation", exit_code=3)
