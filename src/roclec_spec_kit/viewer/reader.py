"""Read-only projections of one profile-3 project for the optional viewer.

Every projection is derived from ``Kernel``, ``Releases`` and ``Verification``.
This module never writes project files, never executes checks and never queries
a remote. Each ``Reader`` is a fresh validated snapshot; callers discard it after
one request so a refresh always rebuilds the model.
"""
from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import re
import subprocess

from ..causality import one_head, scoped_heads
from ..config import load_profile
from ..kernel import Kernel
from ..model import ModelError, digest, fingerprint, identifier, version_key
from ..releases import Releases
from ..verification import Verification, same_context

STAGES = ("approved", "in-progress", "verified", "integrated", "not-evaluated", "canceled")
ID_PATTERN = re.compile(r"\b(?:(?:CHG|CAP|REQ|AC|FUT)-[0-9]{3,}|(?:RUN|EVD)-[0-7][0-9A-HJKMNP-TV-Z]{25})\b")
INVALID_CODES = {"HASH_MISMATCH", "INVALID_INPUT", "UNSUPPORTED_SCHEMA", "INVALID_PATH", "ID_COLLISION",
                 "DECISION_FORK", "VERSION_INVALID", "AMBIGUOUS_EVIDENCE"}


class ViewerError(Exception):
    """A request failure the HTTP layer reports with a stable kind."""

    def __init__(self, kind, code, message, *, status=500, **context):
        super().__init__(message)
        self.kind, self.status = kind, status
        self.payload = {"kind": kind, "code": code, "message": message, **context}


def not_found(message, **context):
    return ViewerError("not_found", "NOT_FOUND", message, status=404, **context)


def classify(exc: ModelError):
    """Map a model failure to a viewer error: absent resource vs invalid record."""
    issue = exc.issue
    missing = issue["code"] == "INVALID_REFERENCE" and "missing" in issue["message"].lower()
    kind, status = ("not_found", 404) if missing else ("invalid_record", 422)
    return ViewerError(kind, issue["code"], issue["message"], status=status, issue=issue)


def git_text(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=15,
                            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    return result.stdout.decode("utf-8", "surrogateescape").strip() if result.returncode == 0 else None


def entities_in(*values):
    found, seen = [], set()
    for value in values:
        for match in ID_PATTERN.findall(str(value) if value is not None else ""):
            if match not in seen:
                seen.add(match)
                found.append(match)
    return found


def title_of(markdown, fallback):
    for line in markdown.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:140]
    return fallback


def repositories(profile):
    repos = {profile.repo(name) for name in profile.components}
    top = git_text(profile.root, "rev-parse", "--show-toplevel")
    if top and Path(top).resolve() == profile.root:
        repos.add(profile.root)
    return sorted(repos)


def state_id(profile, store):
    """Fingerprint of everything a projection may read: records and Git working state."""
    parts = {"records": store.token(), "repos": {}}
    for repo in repositories(profile):
        head = git_text(repo, "rev-parse", "--verify", "-q", "HEAD")
        ref = git_text(repo, "symbolic-ref", "-q", "HEAD")
        result = subprocess.run(["git", "-C", str(repo), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                                capture_output=True, timeout=30, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        entries = []
        for item in filter(None, result.stdout.split(b"\0")):
            name = item[3:].decode("utf-8", "surrogateescape")
            try:
                stat = (repo / name).stat()
                entries.append((item[:2].decode(), name, stat.st_mtime_ns, stat.st_size))
            except OSError:
                entries.append((item[:2].decode(), name, None, None))
        parts["repos"][str(repo)] = {"head": head, "ref": ref, "status": entries}
    return digest(parts)


class Reader:
    def __init__(self, root):
        self.profile = load_profile(Path(root))
        self.kernel = Kernel(self.profile)
        self.store = self.kernel.store
        self.root = self.profile.root
        self.verifier = Verification(self.kernel)
        self._cache = {}

    # ---- Shared lookups -------------------------------------------------

    def _once(self, key, build):
        if key not in self._cache:
            self._cache[key] = build()
        return self._cache[key]

    def component(self, name):
        if name not in self.profile.components:
            raise not_found("Unknown component", entity=name)
        return name

    def releases(self):
        return self._once("releases", self.kernel.releases)

    def release_entry(self, component, version):
        self.component(component)
        try:
            version_key(version, historical=True)
        except ModelError as exc:
            raise ViewerError("not_found", exc.issue["code"], exc.issue["message"], status=404) from exc
        key = version_key(version, historical=True)
        for entry in self.releases():
            if entry["record"]["component"] == component and version_key(entry["record"]["version"], historical=True) == key:
                return entry
        raise not_found("Release not found", entity=f"{component}/{version}")

    def runs(self):
        """(finalized runs by id, unfinished run ids, invalid records)."""
        def build():
            starts, runs, unfinished, invalid = {}, {}, [], []
            for path in sorted(self.store.path(".roclec/runs").glob("RUN-*/start.json")):
                try:
                    started = self.verifier.read_start(path)
                    starts[started["id"]] = started
                    if (path.parent / "manifest.json").is_file():
                        runs[started["id"]] = self.verifier.read_run(started["id"], started=started)
                    else:
                        unfinished.append(started["id"])
                except ModelError as exc:
                    invalid.append({"id": path.parent.name, "issue": exc.issue})
            return {"starts": starts, "runs": runs, "unfinished": unfinished, "invalid": invalid}
        return self._once("runs", build)

    def reports(self):
        def build():
            runs, result, invalid = self.runs()["runs"], {}, []
            for path in sorted(self.store.path(".roclec/evidence").glob("EVD-*.json")):
                try:
                    report = self.verifier.read_evidence(path, runs)
                    if report["kind"] != "finding-decision":
                        result[report["id"]] = report
                except ModelError as exc:
                    invalid.append({"id": path.stem, "issue": exc.issue})
            return {"reports": result, "invalid": invalid}
        return self._once("reports", build)

    def identity(self, name):
        return self._once("registry", self.kernel.registry)["identities"].get(name)

    def contract(self, cap, revision, folder=None):
        try:
            return self.kernel.contract(cap, revision, folder=folder)
        except ModelError as exc:
            raise classify(exc) from exc

    def change_revision(self, change_id, revision):
        identifier(change_id, "CHG")
        fingerprint(revision)
        folder = self.store.path(f".roclec/changes/{change_id}/revisions/{revision}")
        if not (folder / "change.json").is_file():
            raise not_found("Change revision not found", entity=f"{change_id}@{revision[:12]}")
        record, _, _ = self.kernel.change(change_id, source=folder, historical=True)
        return record, folder

    def current_digest(self, change_id):
        path = self.store.path(f".roclec/changes/{change_id}/change.json")
        return self.kernel.read(path.relative_to(self.root).as_posix())["proposal_digest"] if path.is_file() else None

    def proposal_text(self, change_id, revision):
        record, folder = self.change_revision(change_id, revision)
        return record, (folder / record["semantic"]["intention"]).read_text(encoding="utf-8")

    # ---- Project --------------------------------------------------------

    def project(self):
        top = git_text(self.root, "rev-parse", "--show-toplevel")
        branch = git_text(self.root, "symbolic-ref", "-q", "--short", "HEAD")
        head = git_text(self.root, "rev-parse", "--short", "HEAD")
        git_dir, common = git_text(self.root, "rev-parse", "--absolute-git-dir"), git_text(self.root, "rev-parse", "--git-common-dir")
        linked = bool(git_dir and common and Path(git_dir).resolve() != (self.root / common).resolve())
        return {"name": self.profile.data["name"], "root": str(self.root), "branch": branch,
                "detached": branch is None and head is not None, "head": head,
                "worktree": str(self.root) if linked else None, "git_root": top,
                "trunk_ref": self.profile.data["trunk_ref"], "model_schema": 2, "profile_schema": 3,
                "components": [{"name": name, "user_facing": entry["user_facing"], "target_ref": entry["target_ref"],
                                "repo": str(self.profile.repo(name))} for name, entry in sorted(self.profile.components.items())]}

    # ---- Releases -------------------------------------------------------

    def release_list(self, component=None):
        if component is not None:
            self.component(component)
        rows = []
        for entry in self.releases():
            record = entry["record"]
            if component is not None and record["component"] != component:
                continue
            rows.append({"component": record["component"], "version": record["version"], "kind": record["kind"],
                         "status": entry["status"], "members": len(record["changes"]),
                         "published": None if not entry["publication"] else
                         {"commit": entry["publication"]["commit"], "tag": entry["publication"]["tag"]}})
        rows.sort(key=lambda r: (r["component"], version_key(r["version"], historical=True)), reverse=False)
        return {"releases": rows}

    def release_contracts(self, entry):
        """Final contract map for a release: frozen when published, reconstructed otherwise."""
        record = entry["record"]
        if entry["publication"]:
            return {"source": "publication", "contracts": dict(entry["publication"]["contracts"]), "issue": None}
        try:
            context = Releases(self.kernel).context(record["component"], record["version"], unpublished=True)
            return {"source": "release-context", "contracts": dict(context["contracts"]), "issue": None}
        except ModelError as exc:
            # Members that are not integrated yet: show what the approved proposals would define.
            proposed = {}
            for member in record["changes"]:
                try:
                    change, _ = self.change_revision(member["change_id"], member["intent_revision"])
                except ViewerError:
                    continue
                for entry_ in change["semantic"]["proposed"]:
                    if record["component"] in entry_["components"]:
                        proposed[entry_["capability_id"]] = entry_["revision"]
            return {"source": "proposals" if proposed else None, "contracts": proposed, "issue": exc.issue}

    def locate(self, cap, revision, members):
        """A contract revision from the integrated store, else from a member's approved proposal."""
        try:
            return self.find_contract(cap, revision)[:2]
        except ViewerError:
            for member in members:
                try:
                    return self.find_contract(cap, revision, (member["change_id"], member["intent_revision"]))[:2]
                except ViewerError:
                    continue
            raise

    def contract_summary(self, component, contracts, members=()):
        summary = []
        for cap, revision in sorted(contracts.items()):
            try:
                descriptor, files = self.locate(cap, revision, members)
            except ViewerError as exc:
                summary.append({"cap": cap, "revision": revision, "issue": exc.payload.get("issue") or exc.payload, "requirements": []})
                continue
            summary.append({"cap": cap, "revision": revision, "issue": None, "requirements": [
                {"id": r["id"], "title": title_of(files[r["statement"]].decode("utf-8"), r["id"]),
                 "acceptance_ids": [a for a in r["acceptance_ids"] if component in next(
                     x for x in descriptor["acceptance"] if x["id"] == a)["components"]]}
                for r in descriptor["requirements"] if component in r["components"]]})
        return summary

    def release(self, component, version):
        entry = self.release_entry(component, version)
        record, publication = entry["record"], entry["publication"]
        rows = [self.member_row(component, member, published=publication is not None) for member in record["changes"]]
        counts = {stage: 0 for stage in STAGES}
        counts.update(Counter(row["stage"] for row in rows))
        contracts = self.release_contracts(entry)
        result = {"component": component, "version": record["version"], "kind": record["kind"], "base_tag": record["base_tag"],
                  "status": entry["status"], "members": rows, "counts": counts, "total": len(rows),
                  "contracts": self.contract_summary(component, contracts["contracts"], record["changes"]),
                  "contracts_source": contracts["source"], "contracts_issue": contracts["issue"],
                  "policy": None, "gate": None, "publication": None, "preparations": self.preparations(component, record["version"])}
        try:
            policy = Verification(self.kernel, release={"component": component, "version": record["version"]}).policy(None)
            result["policy"] = {"enabled": policy["enabled"], "members": policy["members"]}
        except ModelError as exc:
            result["policy"] = {"enabled": None, "issue": exc.issue}
        if publication:
            result["publication"] = self.publication(component, record["version"], publication)
        else:
            result["gate"] = self.release_gate(component, record["version"], entry["record"], contracts)
        return result

    def preparations(self, component, version):
        rows = []
        releases = Releases(self.kernel)
        for path in sorted(self.store.path(f".roclec/releases/{component}/{version}/preparations").glob("*.json")):
            try:
                prepared = releases.preparation(component, version, path.stem)
                rows.append({"id": path.stem, "run_id": prepared["run_id"], "head": prepared["candidate"]["head"],
                             "evidence_ids": prepared["evidence"], "valid": True, "issue": None})
            except ModelError as exc:
                rows.append({"id": path.stem, "run_id": None, "head": None, "evidence_ids": [], "valid": False, "issue": exc.issue})
        return rows

    def publication(self, component, version, publication):
        evidence = publication["evidence"]
        run_id = evidence.get("run_id")
        runs = self.runs()["runs"]
        return {"commit": publication["commit"], "tag": publication["tag"], "remote": publication["remote"],
                "actor": evidence.get("actor"), "reason": evidence.get("reason"),
                "preparation": evidence.get("preparation"), "run_id": run_id if run_id in runs else None,
                "evidence_ids": [e for e in evidence.get("evidence_ids", []) if e in self.reports()["reports"]],
                "provenance": {"preparation": "preparation" in evidence, "run": run_id in runs, "query": "query" in evidence,
                               "evidence": bool(evidence.get("evidence_ids"))},
                "partial": not ("preparation" in evidence and run_id in runs),
                "note": evidence.get("note")}

    def gate_entities(self, issue, contracts):
        refs = []
        for name in entities_in(issue.get("entity"), issue.get("actual"), issue.get("expected"), issue.get("path")):
            refs.append(self.entity_ref(name, contracts))
        return refs

    def entity_ref(self, name, contracts):
        kind = name.split("-")[0]
        ref = {"kind": kind, "id": name}
        if kind in {"REQ", "AC"}:
            identity = self.identity(name)
            req = name if kind == "REQ" else (identity or {}).get("owner")
            cap = (self.identity(req) or {}).get("owner") if req else None
            if req and cap:
                ref.update(req=req, cap=cap, revision=contracts.get(cap))
        return ref

    def release_gate(self, component, version, record, contracts):
        """Same evaluation as ``check --gate release``; failures keep code, message and fields."""
        base = {"scope": "Final release contract (check --gate release)", "evaluated": True}
        try:
            result = Releases(self.kernel).gate(component, version)
        except ModelError as exc:
            issue = exc.issue
            return {**base, "ok": False, "code": issue["code"], "message": issue["message"], "entity": issue["entity"],
                    "expected": issue["expected"], "actual": issue["actual"], "remediation": issue["remediation"],
                    "path": issue["path"], "entities": self.gate_entities(issue, contracts["contracts"])}
        return {**base, "ok": True, "code": None, "run_id": result["run_id"], "evidence": result["evidence"],
                "head": result["candidate"]["head"], "policy_id": result["policy_id"]}

    # ---- Changes --------------------------------------------------------

    def member_row(self, component, member, *, published):
        change_id, revision = member["change_id"], member["intent_revision"]
        record, text = self.proposal_text(change_id, revision)
        timeline = self.timeline(change_id, component, revision, published=published)
        return {"change_id": change_id, "intent_revision": revision, "kind": record["kind"],
                "title": title_of(text, change_id), "stage": timeline["stage"], "timeline": timeline["steps"],
                "diagnostic": timeline["diagnostic"], "current": self.current_digest(change_id) == revision}

    def timeline(self, change_id, component, revision, *, published=False):
        """Stage line for one (change, component, intent revision) from decisions, runs and integrations."""
        decisions = self.kernel.decisions(change_id)
        approved = next((d for d in decisions if d["kind"] == "change-approve" and d["proposal_digest"] == revision), None)
        canceled = next((d for d in decisions if d["kind"] == "change-cancel" and component in d["components"]
                         and d["proposal_digest"] == revision), None)
        started = next((d for d in decisions if d["kind"] == "change-start" and d.get("component") == component
                        and d["proposal_digest"] == revision), None)
        diagnostic = None
        integration, integration_issue = None, None
        try:
            integration = self.kernel.integration(change_id, component, revision)
        except ModelError as exc:
            integration_issue = exc.issue
        scope_runs = [r for r in self.runs()["runs"].values() if r["change_id"] == change_id and r["component"] == component
                      and r.get("release") is None and r["candidate"]["inputs"]["proposal_digest"] == revision]
        unfinished = [i for i in self.runs()["unfinished"] if (s := self.runs()["starts"][i])["change_id"] == change_id
                      and s["component"] == component and s["candidate"]["inputs"]["proposal_digest"] == revision]
        latest = max(scope_runs, key=lambda r: r["id"], default=None)
        steps = [{"key": "approved", "state": "done" if approved else "pending", "ref": {"kind": "decision", "id": approved["id"]} if approved else None,
                  "detail": approved["actor"] if approved else None, "issue": None}]
        started_ref = {"kind": "decision", "id": started["id"]} if started else ({"kind": "run", "id": latest["id"]} if latest else None)
        steps.append({"key": "started", "state": "done" if (started or latest or unfinished or integration) else "pending",
                      "ref": started_ref, "detail": None, "issue": None})
        verified = {"key": "verified", "state": "pending", "ref": None, "detail": None, "issue": None}
        stage = "approved"
        if integration:
            verified.update(state="done", ref={"kind": "run", "id": integration["run_id"]})
            stage = "integrated"
        elif published or canceled:
            verified.update(state="not-evaluated", detail="Sin registro de verificación para esta revisión")
            stage = "canceled" if canceled else "approved"
        elif latest or unfinished:
            stage = "in-progress"
            if latest is None:
                verified.update(state="blocked", ref={"kind": "run", "id": unfinished[-1]}, detail="Run interrumpido antes de finalizar")
            elif latest["status"] != "pass":
                verified.update(state="blocked", ref={"kind": "run", "id": latest["id"]}, detail=f"Último run: {latest['status']}")
            elif self.current_digest(change_id) != revision:
                verified.update(state="not-evaluated", ref={"kind": "run", "id": latest["id"]},
                                detail="Revisión sustituida: el gate vivo solo evalúa la propuesta vigente")
            else:
                try:
                    self.kernel.gate(change_id, component, "verify")
                    verified.update(state="done", ref={"kind": "run", "id": latest["id"]})
                    stage = "verified"
                except ModelError as exc:
                    verified.update(state="blocked", ref={"kind": "run", "id": latest["id"]}, detail=exc.issue["message"], issue=exc.issue)
                    diagnostic = exc.issue
                except Exception as exc:  # noqa: BLE001 - an unreadable Git state is "not evaluated", not a failure.
                    verified.update(state="not-evaluated", ref={"kind": "run", "id": latest["id"]}, detail="No se pudo evaluar el gate")
                    stage = "not-evaluated"
        elif started:
            stage = "in-progress"
        steps.append(verified)
        steps.append({"key": "integrated", "state": "done" if integration else "canceled" if canceled else "pending",
                      "ref": {"kind": "integration", "id": integration["digest"]} if integration else None,
                      "detail": integration["target_commit"][:12] if integration else None, "issue": integration_issue})
        if integration_issue:
            diagnostic = integration_issue
        if canceled:
            stage = "canceled"
        return {"stage": stage, "steps": steps, "diagnostic": diagnostic}

    def requirement_changes(self, record, folder):
        """Affected requirements of an approved revision: deltas for evolutions, bases for preservation."""
        semantic = record["semantic"]
        proposed = {p["capability_id"]: p for p in semantic["proposed"]}
        rows = []
        for delta in semantic["deltas"]:
            cap = delta["capability_id"]
            ids = ([delta["old_requirement"], delta["new_requirement"]] if delta["op"] == "replace" else [delta["requirement_id"]])
            bases = [b for b in semantic["bases"] if b["capability_id"] == cap]
            for req in ids:
                in_proposal = delta["op"] != "retire" and req != delta.get("old_requirement")
                rows.append({"op": delta["op"], "req": req, "cap": cap, "components": proposed[cap]["components"],
                             "proposed_revision": proposed[cap]["revision"] if in_proposal else None,
                             "base_revisions": sorted({b["revision"] for b in bases if b["revision"]}),
                             "retire_acceptance_ids": delta.get("retire_acceptance_ids", []),
                             "add_acceptance_ids": delta.get("add_acceptance_ids", [])})
        return rows

    def preserved(self, record, folder):
        """Fix/refactor changes: base contracts and their declared scope."""
        rows = []
        for base in record["semantic"]["bases"]:
            if base["revision"] is None:
                continue
            try:
                descriptor, files = self.kernel.contract(base["capability_id"], base["revision"])
            except ModelError as exc:
                rows.append({"cap": base["capability_id"], "component": base["component"], "revision": base["revision"], "issue": exc.issue, "requirements": []})
                continue
            rows.append({"cap": base["capability_id"], "component": base["component"], "revision": base["revision"], "issue": None,
                         "requirements": [{"id": r["id"], "title": title_of(files[r["statement"]].decode("utf-8"), r["id"]), "acceptance_ids": r["acceptance_ids"]}
                                          for r in descriptor["requirements"] if base["component"] in r["components"]]})
        return rows

    def change(self, change_id, revision=None, component=None):
        identifier(change_id, "CHG")
        current = self.current_digest(change_id)
        if current is None and revision is None:
            raise not_found("Change not found", entity=change_id)
        revision = revision or current
        record, text = self.proposal_text(change_id, revision)
        if component is not None and component not in record["semantic"]["components"]:
            raise ViewerError("not_found", "NOT_FOUND", "Component is outside change scope", status=404, entity=f"{change_id}/{component}")
        decisions = self.kernel.decisions(change_id)
        approval = next((d for d in reversed(decisions) if d["kind"] == "change-approve" and d["proposal_digest"] == revision), None)
        folder = self.store.path(f".roclec/changes/{change_id}/revisions/{revision}")
        revisions = sorted(p.name for p in self.store.path(f".roclec/changes/{change_id}/revisions").glob("*") if p.is_dir())
        assigned = [{"component": e["record"]["component"], "version": e["record"]["version"], "status": e["status"]}
                    for e in self.releases() for m in e["record"]["changes"] if m["change_id"] == change_id and m["intent_revision"] == revision]
        scope = record["semantic"]["components"]
        stages = {c: self.timeline(change_id, c, revision, published=any(a["component"] == c and a["status"] == "published" for a in assigned))
                  for c in scope}
        return {"id": change_id, "revision": revision, "kind": record["kind"], "title": title_of(text, change_id),
                "intention": text, "components": scope, "current": current == revision, "current_revision": current,
                "revisions": [{"revision": r, "current": r == current} for r in revisions],
                "approval": {"id": approval["id"], "actor": approval["actor"], "reason": approval["reason"]} if approval else None,
                "stages": {c: {"stage": s["stage"], "steps": s["steps"], "diagnostic": s["diagnostic"]} for c, s in stages.items()},
                "requirements": self.requirement_changes(record, folder), "preserved": self.preserved(record, folder) if record["kind"] != "evolution" else [],
                "fixes": record["semantic"].get("fixes", []), "baseline_release": record["semantic"].get("baseline_release"),
                "releases": assigned, "dependencies": record["semantic"]["dependencies"]}

    # ---- Requirements and coverage -------------------------------------

    def find_contract(self, cap, revision, change=None):
        """Resolve a contract revision from the integrated store or a change's approved snapshot."""
        identifier(cap, "CAP")
        fingerprint(revision)
        folder = self.store.path(f".roclec/contracts/{cap}/{revision}")
        if (folder / "contract.json").is_file():
            descriptor, files = self.contract(cap, revision)
            return descriptor, files, "integrated"
        if change:
            change_id, intent = change
            _, base = self.change_revision(change_id, intent)
            proposed = base / f"proposed/{cap}/{revision}"
            if (proposed / "contract.json").is_file():
                descriptor, files = self.contract(cap, revision, folder=proposed)
                return descriptor, files, "proposal"
        raise not_found("Contract revision not found", entity=f"{cap}@{revision[:12]}")

    def scope_contracts(self, component, *, release=None, change=None):
        """The contract revisions that define the obligations of a scope."""
        if release:
            entry = self.release_entry(component, release)
            found = self.release_contracts(entry)
            return found["contracts"], found["issue"]
        change_id, intent = change
        record, folder = self.change_revision(change_id, intent)
        contracts = {}
        for base in record["semantic"]["bases"]:
            if base["component"] == component and base["revision"]:
                contracts[base["capability_id"]] = base["revision"]
        for proposed in record["semantic"]["proposed"]:
            if component in proposed["components"]:
                contracts[proposed["capability_id"]] = proposed["revision"]
        return contracts, None

    def acceptance_for(self, component, contracts, change=None):
        found = {}
        for cap, revision in contracts.items():
            descriptor, files, _ = self.find_contract(cap, revision, change)
            for ac in descriptor["acceptance"]:
                if component in ac["components"]:
                    found[ac["id"]] = {"cap": cap, "revision": revision}
        return found

    def coverage(self, component, *, release=None, change=None):
        """Per-criterion state for one scope without raising on an unfavorable result."""
        contracts, contract_issue = self.scope_contracts(component, release=release, change=change)
        acs = self.acceptance_for(component, contracts, change)
        published = False
        if release:
            entry = self.release_entry(component, release)
            published = entry["publication"] is not None
            scope_key = (None, component, release)
        else:
            scope_key = (change[0], component, None)
        runs = self.runs()
        attempts = [s for s in runs["starts"].values() if (s["change_id"], s["component"], (s.get("release") or {}).get("version")) == scope_key]
        if change:
            attempts = [s for s in attempts if s["candidate"]["inputs"]["proposal_digest"] == change[1]]
        report_pool = [r for r in self.reports()["reports"].values()
                       if (r["change_id"], r["component"], (r.get("release") or {}).get("version")) == scope_key
                       and (not change or r["run_id"] in {s["id"] for s in attempts})]
        stop, run, candidate_state = None, None, "unknown"
        latest = None
        heads = {}
        try:
            heads = scoped_heads(attempts, lambda _: ["run"]) if attempts else {}
            latest = one_head(heads, "run") if attempts else None
        except ModelError as exc:
            stop = exc.issue
        if published:
            pub = self.release_entry(component, release)["publication"]["evidence"]
            wanted = pub.get("run_id")
            latest = next((s for s in attempts if s["id"] == wanted), None)
            if latest is None:
                stop = {"code": "PROVENANCE_PARTIAL", "message": "La publicación no conserva el run que respalda sus criterios"}
        if stop is None and latest is None:
            stop = {"code": "COVERAGE_MISSING", "message": "No verification run for this component"}
        if stop is None:
            if latest["id"] in runs["runs"]:
                run = runs["runs"][latest["id"]]
                candidate_state = "recorded"
            else:
                stop = {"code": "CANDIDATE_INCOMPLETE", "message": "El último run se interrumpió antes de finalizar", "entity": latest["id"]}
        if run is not None and not published:
            candidate_state = self.candidate_state(component, run, release, change)
            if candidate_state == "stale":
                stop = {"code": "EVIDENCE_STALE", "message": "Relevant candidate inputs changed", "entity": run["id"]}
            elif candidate_state == "unknown":
                stop = {"code": "CANDIDATE_INCOMPLETE", "message": "No se pudo capturar el candidato actual", "entity": run["id"]}
        results = run["results"] if run else []
        by_ac = {}
        for result in results:
            for ac in result["acceptance_ids"]:
                by_ac.setdefault(ac, []).append({"id": result["id"], "status": result["status"], "returncode": result["returncode"],
                                                 "run_id": run["id"]})
        report_heads = {}
        try:
            report_heads = scoped_heads(report_pool, self.verifier.report_scopes) if report_pool else {}
        except ModelError as exc:
            stop = stop or exc.issue
        head_ids = {r["id"] for items in report_heads.values() for r in items}
        reports = []
        for report in sorted(report_pool, key=lambda r: r["id"]):
            current = run is not None and report["candidate_digest"] == run["candidate"]["inputs_digest"]
            state = ("superseded" if report["id"] not in head_ids else "stale" if not current else
                     "applicable" if report["outcome"] in {"pass", "ready"} and report["checks"] else "unfavorable")
            uncounted = None
            if report["kind"] == "independent-review" and state == "applicable" and not published:
                # Same rule as the verify gate: a favorable review counts only with a declared role and
                # a context that differs from the producer of the cited run and of the gated run.
                cited = runs["runs"].get(report["run_id"])
                producers = [cited.get("producer") if cited else None, run.get("producer")]
                if "role" not in report or None in producers:
                    uncounted = "unattributed"
                elif any(same_context(report["context"], p["context"]) for p in producers):
                    uncounted = "self-review-declared"
                if uncounted:
                    state = "stale"
            reports.append({"id": report["id"], "kind": report["kind"], "outcome": report["outcome"], "actor": report["actor"],
                            "acceptance_ids": report["acceptance_ids"], "state": state, "run_id": report["run_id"],
                            "role": report.get("role"), "uncounted": uncounted})
        by_report = {r["id"]: r for r in reports}
        criteria = {}
        for ac in sorted(acs):
            checks = by_ac.get(ac, [])
            obs = []
            ambiguous = False
            try:
                head = one_head(report_heads, ("observation", ac))
                if head:
                    obs = [by_report[head["id"]]]
            except ModelError:
                ambiguous = True
            refs = [by_report[r["id"]] for r in report_pool if ac in r["acceptance_ids"] and r["kind"] != "independent-review"]
            if ambiguous:
                state = "ambiguous"
            elif run is None and not any(c["status"] == "fail" for c in checks):
                state = "not-evaluated" if stop and stop["code"] != "COVERAGE_MISSING" else "pending"
            elif any(c["status"] == "fail" for c in checks):
                state = "unfavorable"
            elif run is not None and run["status"] == "interrupted":
                state = "interrupted"
            elif stop is not None:
                state = "not-evaluated"
            else:
                state = "covered" if any(c["status"] == "pass" for c in checks) else "pending"
                if obs and obs[0]["state"] == "applicable":
                    state = "covered"
                elif obs and obs[0]["state"] == "unfavorable":
                    state = "unfavorable"
                elif obs and obs[0]["state"] == "stale":
                    state = "stale"
            criteria[ac] = {"state": state, "checks": checks, "reports": [{"id": r["id"], "state": r["state"], "outcome": r["outcome"]} for r in refs]}
        review = self.review_state(component, release, change, reports, report_heads, run)
        superseded_runs = [{"id": s["id"], "state": "superseded"} for s in attempts if latest and s["id"] != latest["id"]]
        return {"scope": {"release": release, "change": change[0] if change else None, "revision": change[1] if change else None},
                "component": component, "contracts": contracts, "contract_issue": contract_issue, "criteria": criteria, "ac_info": acs,
                "run": None if run is None else self.run_summary(run), "latest_attempt": latest["id"] if latest else None,
                "stop": stop, "candidate": candidate_state, "reports": reports, "superseded_runs": superseded_runs,
                "review": review, "published": published}

    def candidate_state(self, component, run, release, change):
        try:
            scope = Verification(self.kernel, release={"component": component, "version": release} if release else None)
            current = scope.candidate(change[0] if change else None, component, run["candidate"]["base"])
        except (ModelError, OSError, subprocess.SubprocessError):
            return "unknown"
        return "current" if current["inputs_digest"] == run["candidate"]["inputs_digest"] else "stale"

    def review_state(self, component, release, change, reports, heads, run):
        try:
            policy = Verification(self.kernel, release={"component": component, "version": release} if release else None).policy(
                None if release else change[0])
        except ModelError as exc:
            return {"required": None, "issue": exc.issue}
        if not policy or not policy["enabled"]:
            return {"required": False, "state": "not-required", "reviews": []}
        reviews = [r for r in reports if r["kind"] == "independent-review" and r["state"] != "superseded"]
        favorable = [r for r in reviews if r["state"] == "applicable"]
        state = "pending" if not reviews else "changes-needed" if any(r["outcome"] == "changes-needed" for r in reviews) else \
            "ready" if favorable and len(favorable) == len(reviews) else "stale"
        return {"required": True, "state": state, "reviews": reviews}

    def run_summary(self, run):
        return {"id": run["id"], "status": run["status"], "limitations": run["limitations"], "head": run["candidate"]["head"],
                "inputs_digest": run["candidate"]["inputs_digest"]}

    def requirement(self, req, cap, revision, component=None, release=None, change=None, release_component=None):
        identifier(req, "REQ")
        descriptor, files, source = self.find_contract(cap, revision, change)
        entry = next((r for r in descriptor["requirements"] if r["id"] == req), None)
        if entry is None:
            raise not_found("Requirement is not part of this contract revision", entity=f"{req}@{cap}")
        if component is not None and component not in entry["components"]:
            raise not_found("Requirement does not apply to this component", entity=f"{req}/{component}")
        by_component = {}
        for name in entry["components"]:
            by_component[name] = self.component_coverage(name, entry, descriptor, files, release=release, change=change)
        acceptance = [{"id": a["id"], "components": a["components"], "scenario": files[a["scenario"]].decode("utf-8")}
                      for a in descriptor["acceptance"] if a["id"] in entry["acceptance_ids"]]
        return {"id": req, "cap": cap, "revision": revision, "source": source, "components": entry["components"],
                "statement": files[entry["statement"]].decode("utf-8"), "acceptance": acceptance,
                "identity": self.identity(req), "coverage": by_component,
                "context": {"release": release, "release_component": release_component or component, "change": change[0] if change else None,
                            "intent": change[1] if change else None}}

    def component_coverage(self, component, entry, descriptor, files, *, release, change):
        scope_release = release
        scope_change = change
        try:
            if release is None and change is None:
                return {"state": "no-scope", "criteria": {}, "message": "Sin contexto de release o cambio no hay cobertura que evaluar"}
            data = self.coverage(component, release=scope_release, change=scope_change)
        except (ViewerError, ModelError) as exc:
            message = exc.payload["message"] if isinstance(exc, ViewerError) else exc.issue["message"]
            return {"state": "unavailable", "criteria": {}, "message": message}
        criteria = {ac: data["criteria"][ac] for ac in entry["acceptance_ids"] if ac in data["criteria"]}
        return {"state": "evaluated", "criteria": criteria, "run": data["run"], "stop": data["stop"], "candidate": data["candidate"],
                "review": data["review"], "reports": [r for r in data["reports"] if set(r["acceptance_ids"]) & set(entry["acceptance_ids"])
                                                        or r["kind"] == "independent-review"],
                "superseded_runs": data["superseded_runs"], "published": data["published"], "contracts": data["contracts"]}

    # ---- Evidence -------------------------------------------------------

    def criteria_links(self, component, release, change_id, intent, acceptance_ids):
        """Resolve criteria to (requirement, capability, contract revision) inside the scope that produced them."""
        try:
            change = (change_id, intent) if change_id and intent else None
            contracts, _ = self.scope_contracts(component, release=release, change=change)
            links = []
            for cap, revision in sorted(contracts.items()):
                descriptor, _, _ = self.find_contract(cap, revision, change)
                for req in descriptor["requirements"]:
                    for ac in req["acceptance_ids"]:
                        if ac in acceptance_ids and component in req["components"]:
                            links.append({"ac": ac, "req": req["id"], "cap": cap, "revision": revision})
            return sorted(links, key=lambda l: l["ac"])
        except (ViewerError, ModelError):
            return []

    def evidence_run(self, run_id):
        identifier(run_id, "RUN")
        runs = self.runs()
        if run_id not in runs["starts"]:
            raise not_found("Run not found", entity=run_id)
        started = runs["starts"][run_id]
        if run_id not in runs["runs"]:
            return {"type": "run", "id": run_id, "status": "unfinished", "component": started["component"], "change_id": started["change_id"],
                    "release": started.get("release"), "candidate": self.candidate_view(started["candidate"]), "checks": [],
                    "limitations": ["El run se interrumpió antes de finalizar"], "supersedes": started["supersedes"], "executed_by_roclec": True,
                    "reports": [], "superseded_by": [], "scope": self.run_scope(started), "criteria": []}
        run = runs["runs"][run_id]
        return {"type": "run", "id": run_id, "status": run["status"], "component": run["component"], "change_id": run["change_id"],
                "release": run.get("release"), "candidate": self.candidate_view(run["candidate"]),
                "checks": [{"id": r["id"], "argv": r["argv"], "cwd": r["cwd"], "status": r["status"], "returncode": r["returncode"],
                            "duration_seconds": r["duration_seconds"], "acceptance_ids": r["acceptance_ids"],
                            "executed_by_roclec": r["executed_by_roclec"], "limitation": r.get("limitation"),
                            "environment": r["environment"],
                            "logs": {label: {"size": r[label]["size"], "complete": r[label]["complete"], "sha256": r[label]["sha256"]}
                                     for label in ("stdout", "stderr")}} for r in run["results"]],
                "limitations": run["limitations"], "supersedes": run["supersedes"], "executed_by_roclec": True, "tools": run["tools"],
                "digest": run["digest"], "superseded_by": sorted(s["id"] for s in runs["starts"].values() if run_id in s["supersedes"]),
                "reports": [{"id": r["id"], "kind": r["kind"], "outcome": r["outcome"]} for r in self.reports()["reports"].values() if r["run_id"] == run_id],
                "scope": self.run_scope(run),
                "criteria": self.criteria_links(run["component"], (run.get("release") or {}).get("version"), run["change_id"],
                                                run["candidate"]["inputs"]["proposal_digest"] if run["change_id"] else None,
                                                {ac for r in run["results"] for ac in r["acceptance_ids"]})}

    @staticmethod
    def run_scope(run):
        release = (run.get("release") or {}).get("version")
        return {"component": run["component"], "release": release, "change": run["change_id"],
                "intent": run["candidate"]["inputs"]["proposal_digest"] if run["change_id"] else None}

    @staticmethod
    def candidate_view(candidate):
        return {"head": candidate["head"], "base": candidate["base"], "dirty": candidate["dirty"], "inputs_digest": candidate["inputs_digest"],
                "files": len([c for c in candidate["categories"].values() if c == "input"]), "paths": len(candidate["categories"])}

    def evidence_report(self, evidence_id):
        identifier(evidence_id, "EVD")
        report = self.reports()["reports"].get(evidence_id)
        if report is None:
            if any(i["id"] == evidence_id for i in self.reports()["invalid"]):
                raise ViewerError("invalid_record", "INVALID_RECORD", "Evidence record is invalid", status=422,
                                  issue=next(i["issue"] for i in self.reports()["invalid"] if i["id"] == evidence_id))
            raise not_found("Evidence report not found", entity=evidence_id)
        same = [r for r in self.reports()["reports"].values() if evidence_id in r["supersedes"]]
        run = self.runs()["runs"].get(report["run_id"])
        stale = run is not None and report["candidate_digest"] != run["candidate"]["inputs_digest"]
        return {"type": "report", "id": evidence_id, "kind": report["kind"], "outcome": report["outcome"], "actor": report["actor"],
                "context": report["context"], "component": report["component"], "change_id": report["change_id"],
                "release": report.get("release"), "run_id": report["run_id"], "candidate_digest": report["candidate_digest"],
                "acceptance_ids": report["acceptance_ids"], "checks": report["checks"], "limitations": report["limitations"],
                "findings": report["findings"], "supersedes": report["supersedes"], "superseded_by": sorted(r["id"] for r in same),
                "state": "superseded" if same else "stale" if stale else "current", "executed_by_roclec": False, "digest": report["digest"],
                "scope": self.run_scope(run) if run else {"component": report["component"], "release": (report.get("release") or {}).get("version"),
                                                           "change": report["change_id"], "intent": None},
                "criteria": self.criteria_links(report["component"], (report.get("release") or {}).get("version"), report["change_id"],
                                                run["candidate"]["inputs"]["proposal_digest"] if run and report["change_id"] else None,
                                                set(report["acceptance_ids"]))}

    def evidence_check(self, run_id, check_id):
        run = self.evidence_run(run_id)
        check = next((c for c in run["checks"] if c["id"] == check_id), None)
        if check is None:
            raise not_found("Check not found in run", entity=f"{run_id}/{check_id}")
        return {**run, "type": "check", "check": check}
