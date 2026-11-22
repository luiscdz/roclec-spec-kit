"""Candidate capture, executed checks and explicitly attributed observations.

Git is queried without a shell. Unknown/ignored paths are classified before any
content is read. Reports express claims; they cannot manufacture Roclec runs.
"""
from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path
import shutil
import subprocess

from .causality import one_head, record_id, scoped_heads
from .config import DEFAULT_LOG_QUOTA
from .run_logs import execute as execute_check
from .model import (ModelError, digest, encoded, fields, fingerprint, identifier,
                    local_path, need, read_json, schema, sha, strings, text, version_key)


def git(repo, *args, check=True):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=30)
    need(not check or result.returncode == 0, "CANDIDATE_INCOMPLETE", "Git candidate query failed",
         actual=result.stderr.decode("utf-8", "replace"))
    if not check:
        return result
    output = result.stdout.decode("utf-8", "surrogateescape")
    return output if "-z" in args else output.strip()


def matches(path, patterns):
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


# Declared producers (M-28): canonical agent roles plus `human`. The coordinator
# may implement small changes itself; only a reviewer or a human may review.
RUN_ROLES = ("coordinator", "human", "implementer")
REVIEW_ROLES = ("human", "reviewer")
RERUN_ATTRIBUTED = ("Rerun `run verify` with --role ROLE --context CONTEXT for this scope "
                    "and record the review against that run.")
SEPARATE_CONTEXT = ("Produce the review in a separate context (the roclec-reviewer role) and declare that context; "
                    "Roclec compares declared contexts, not real independence.")


def single_line(value):
    return text(value) and value.splitlines() == [value]


def declared(role, context, allowed, what):
    need(role in allowed, "INVALID_INPUT", f"Unknown {what} role", exit_code=2, expected=list(allowed), actual=role,
         remediation="Declare one of: " + ", ".join(allowed))
    need(single_line(context), "INVALID_INPUT", f"Declare the actual {what} context as non-empty single-line text",
         exit_code=2, remediation="Use the session or tool identity that actually produced the record.")


def same_context(first, second):
    return first.strip().casefold() == second.strip().casefold()


def read_producer(record):
    if "producer" in record:
        fields(record["producer"], ("role", "context"))
        declared(record["producer"]["role"], record["producer"]["context"], RUN_ROLES, "run")


class Verification:
    def __init__(self, kernel, *, release=None):
        self.k = kernel
        self.store = kernel.store
        self.release = release

    def extras(self):
        return {"release": self.release} if self.release else {}

    def target(self, change_id):
        if not self.release:
            return self.k.change(change_id)[0]
        from .releases import Releases
        context = Releases(self.k).context(**self.release)
        return {"id": None, "proposal_digest": digest(context), "semantic": {"components": [self.release["component"]]},
                "release_context": context}

    def same_scope(self, record, change_id, component):
        return (record["change_id"], record["component"], record.get("release")) == (change_id, component, self.release)

    def policy(self, change_id):
        if self.release:
            release = self.k.release(**self.release)["record"]
            policies = {m["change_id"]: Verification(self.k).policy(m["change_id"]) for m in release["changes"]}
            adopted = {c: p["id"] for c, p in policies.items() if p and p["enabled"]}
            return {"id": digest(adopted), "enabled": bool(adopted), "members": adopted}
        records = [d for d in self.k.decisions(change_id) if d["kind"] == "review-policy"]
        return records[-1] if records else None

    def set_policy(self, change_id, enabled, actor, reason):
        record, _, _ = self.k.change(change_id)
        need(type(enabled) is bool, "INVALID_INPUT", "enabled must be boolean", exit_code=2)
        decision, path = self.k._decision("review-policy", change_id, actor, reason,
                                         proposal_digest=record["proposal_digest"], enabled=enabled)
        receipt = self.store.apply("review-policy", {"id": change_id, "decision": decision["id"]},
                                   {path: encoded(decision)}, self.k.token)
        return {"policy": decision, "receipt": receipt}

    def acceptance(self, record, component):
        contracts = {}
        if self.release:
            contracts = {cap: self.k.contract(cap, rev)[0] for cap, rev in record["release_context"]["contracts"].items()}
            return sorted({a["id"] for c in contracts.values() for a in c["acceptance"] if component in a["components"]})
        semantic = record["semantic"]
        for base in semantic["bases"]:
            if base["component"] == component and base["revision"]:
                contracts[base["capability_id"]] = self.k.contract(base["capability_id"], base["revision"])[0]
        for proposed in semantic["proposed"]:
            if component in proposed["components"]:
                folder = self.store.path(f".roclec/changes/{record['id']}/proposed/{proposed['capability_id']}/{proposed['revision']}")
                contracts[proposed["capability_id"]] = self.k.contract(proposed["capability_id"], proposed["revision"], folder=folder)[0]
        return sorted({a["id"] for c in contracts.values() for a in c["acceptance"] if component in a["components"]})

    def candidate(self, change_id, component, base, *, final=False):
        record = self.target(change_id)
        self.k._component(record, component)
        repo = self.k.profile.repo(component)
        need(repo.is_dir() and Path(git(repo, "rev-parse", "--show-toplevel")).resolve() == repo,
             "CANDIDATE_INCOMPLETE", "Configured repo must be a Git root", entity=component)
        need(text(base) and not base.startswith("-"), "INVALID_INPUT", "Specify a Git base", exit_code=2)
        base_commit = git(repo, "rev-parse", "--verify", f"{base}^{{commit}}")
        head = git(repo, "rev-parse", "--verify", "HEAD^{commit}")
        ancestry = git(repo, "merge-base", "--is-ancestor", base_commit, head, check=False)
        need(ancestry.returncode == 0, "CANDIDATE_INCOMPLETE", "Candidate does not descend from its base")
        status = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
        need(not final or not status, "CANDIDATE_DIRTY", "Commit all pending changes in the affected code repository",
             entity=component, actual=status)
        configured = [v for c, v in self.k.profile.components.items() if self.k.profile.repo(c) == repo]
        paths = set()
        for args in (("ls-files", "-z", "--cached", "--others", "--exclude-standard"),
                     ("ls-files", "-z", "--others", "--ignored", "--exclude-standard"),
                     ("ls-tree", "-r", "--name-only", "-z", base_commit),
                     ("diff", "--name-only", "-z", base_commit, "HEAD")):
            paths.update(filter(None, git(repo, *args).split("\0")))
        refs = self.k.foundation(component, change_id)
        need(not refs["issues"], "FOUNDATION_INCOMPLETE", "Candidate needs agreed references", actual=refs["issues"])
        reference_paths = {(self.k.profile.root / r["path"]).resolve() for r in refs["references"]}
        # ADRs of this component are classified like its references; their state is the ADR gate's concern.
        reference_paths |= {(self.k.profile.root / r["path"]).resolve() for r in self.k.references().values()
                            if r["role"] == "decision" and component in r["components"]}
        files, categories, unknown = {}, {}, []
        for relative in sorted(paths):
            # Operational records do not attest code or invalidate themselves.
            absolute = repo / relative
            if absolute.is_relative_to(self.k.profile.root / ".roclec/runtime"):
                continue
            metadata = absolute.is_relative_to(self.k.profile.root / ".roclec") or absolute.is_relative_to(self.k.profile.root / "specs/capabilities")
            if metadata:
                categories[relative] = "operational"
                continue
            is_input = any(matches(relative, c["inputs"]) for c in configured) or absolute.resolve() in reference_paths or relative == ".gitignore"
            ignored = any(matches(relative, c["generated"] + c.get("excluded", [])) for c in configured)
            need(not (is_input and ignored), "CANDIDATE_INCOMPLETE", "Input overlaps generated/excluded classification", path=relative)
            if not is_input:
                categories[relative] = "excluded" if ignored else "unclassified"
                if not ignored:
                    unknown.append(relative)
                continue
            path = local_path(repo, relative)
            need(not path.exists() or path.is_file(), "CANDIDATE_INCOMPLETE", "Unsupported input type", path=relative)
            categories[relative] = "input"
            files[relative] = ({"type": "file", "mode": path.stat().st_mode & 0o777,
                                "sha256": sha(path.read_bytes())} if path.exists() else {"type": "deleted"})
        need(not unknown, "CANDIDATE_INCOMPLETE", "Classify every path before declaring a candidate sufficient",
             actual=unknown, remediation="Declare sources in inputs, outputs in generated and explicit non-inputs in excluded; unknown bytes were not read.")
        inputs = {"component": component, "repo": self.k.profile.components[component]["repo"],
                  "base": base_commit, "files": files, "profile": self.k.profile.data,
                  "proposal_digest": record["proposal_digest"], "references": refs["references"]}
        tools = {}
        for check in self.k.profile.components[component]["verification"]:
            command = check["argv"][0]
            executable = ((repo / check["cwd"] / command).resolve() if "/" in command
                          else Path(shutil.which(command)).resolve() if shutil.which(command) else None)
            tools[check["id"]] = ({"path": str(executable), "sha256": sha(executable.read_bytes())}
                                  if executable and executable.is_file() else None)
        inputs["tools"] = tools
        if self.release:
            inputs["release"] = record["release_context"]
        return {"model_schema": 2, "change_id": change_id, "component": component,
                "head": head, "base": base_commit, "dirty": bool(status), "categories": categories,
                "inputs": inputs, "inputs_digest": digest(inputs), **self.extras()}

    @staticmethod
    def report_scopes(report):
        if report["kind"] == "independent-review":
            return [("review", report["actor"])]
        return [("observation", ac) for ac in report["acceptance_ids"]]

    @staticmethod
    def run_heads(attempts):
        return scoped_heads(attempts, lambda _: ["run"])

    def run(self, change_id, component, base, role, context):
        declared(role, context, RUN_ROLES, "run")
        producer = {"role": role, "context": context}
        if self.release:
            from .releases import Releases
            Releases(self.k).context(**self.release, unpublished=True)
        else:
            self.k.gate(change_id, component, "implement")
        before = self.candidate(change_id, component, base)
        checks = self.k.profile.components[component]["verification"]
        applicable = self.acceptance(self.target(change_id), component)
        for check in checks:
            need(set(check.get("acceptance_ids", [])) <= set(applicable), "INVALID_REFERENCE", "Check cites an inapplicable AC", entity=check["id"])
        run_id = record_id("RUN")
        previous = self.run_heads(self.attempts(change_id, component)).get("run", [])
        root = f".roclec/runs/{run_id}"
        started = {"model_schema": 2, "id": run_id, "change_id": change_id, "component": component,
                   "candidate": before, "status": "incomplete", "checks": checks,
                   "supersedes": [run["id"] for run in previous], "producer": producer, **self.extras()}
        started["digest"] = digest(started)
        self.store.apply("run-start", {"id": run_id}, {f"{root}/start.json": encoded(started)}, self.k.token)
        execution_token = self.store.token()
        results, interrupted = [], False
        log_root = f".roclec/runtime/logs/{run_id}"
        profile = self.k.profile.data
        quota = profile.get("log_quota_bytes", DEFAULT_LOG_QUOTA)
        for index, check in enumerate(checks):
            cwd = self.k.profile.repo(component) / check["cwd"]
            result, size = execute_check(self.store, check, cwd, log_root, index, profile, quota)
            quota -= size
            results.append(result)
            interrupted = result["status"] == "interrupted"
            if interrupted or result.get("limitation") in {"log quota exceeded", "log write failed", "log read failed"}:
                break
        limitations = []
        try:
            after = self.candidate(change_id, component, before["base"])
            if before["inputs_digest"] != after["inputs_digest"]:
                limitations.append("inputs changed during verification")
        except ModelError as exc:
            limitations.append(exc.issue)
        completion_token = self.store.token()
        if completion_token != execution_token:
            limitations.append("project records changed during verification")
        status = ("interrupted" if interrupted else "incomplete" if limitations or any(r["status"] == "incomplete" for r in results)
                  else "fail" if any(r["status"] == "fail" for r in results) else "pass")
        manifest = {"model_schema": 2, "id": run_id, "change_id": change_id, "component": component,
                    "candidate": before, "status": status, "results": results, "limitations": limitations,
                    "tools": before["inputs"]["tools"], "supersedes": started["supersedes"], "producer": producer, **self.extras()}
        manifest["digest"] = digest(manifest)
        writes = {f"{root}/manifest.json": encoded(manifest)}
        need(not self.store.path(f"{root}/manifest.json").exists(), "OPERATION_CONFLICT", "Run was already finalized", exit_code=3)
        receipt = self.store.apply("run-verify", {"id": run_id}, writes, completion_token)
        # Re-open to include our own records, but never run checks in a gate.
        from .kernel import Kernel
        issues = []
        try:
            from .config import load_profile
            fresh = Verification(Kernel(load_profile(self.k.profile.root)), release=self.release)
            fresh.verify(change_id, component, run_id=run_id)
        except ModelError as exc:
            issues.append(exc.issue)
        except (OSError, ValueError) as exc:
            issues.append(ModelError("CANDIDATE_INCOMPLETE", "Run recorded, but current project cannot be validated", actual=str(exc)).issue)
        return {"recorded": True, "run": manifest, "receipt": receipt, "issues": issues,
                "exit_code": 130 if interrupted else 1 if issues else 0}

    def read_run(self, run_id, *, started=None):
        identifier(run_id, "RUN")
        record = self.k.read(f".roclec/runs/{run_id}/manifest.json")
        fields(record, ("model_schema", "id", "change_id", "component", "candidate", "status", "results", "limitations", "tools", "digest",
                        "supersedes"), ("release", "producer"))
        need(record["id"] == run_id and record["digest"] == digest({k: v for k, v in record.items() if k != "digest"}),
             "HASH_MISMATCH", "Run manifest integrity mismatch")
        if started is None:
            started = self.read_start(self.store.path(f".roclec/runs/{run_id}/start.json"))
        need(started.get("digest") == digest({k: v for k, v in started.items() if k != "digest"})
             and all(started.get(k) == record[k] for k in ("id", "change_id", "component", "candidate", "supersedes"))
             and started.get("producer") == record.get("producer"),
             "HASH_MISMATCH", "Run differs from its reserved candidate")
        need(record["status"] in {"pass", "fail", "incomplete", "interrupted"}
             and isinstance(record["results"], list) and isinstance(record["limitations"], list),
             "INVALID_INPUT", "Invalid run status/results", exit_code=2)
        read_producer(record)
        if "release" in record:
            fields(record["release"], ("component", "version"))
            version_key(record["release"]["version"])
            need(record["change_id"] is None and record["release"]["component"] == record["component"], "INVALID_REFERENCE", "Invalid release run scope")
        else:
            identifier(record["change_id"], "CHG")
        need(record["component"] in self.k.profile.components, "INVALID_REFERENCE", "Unknown run component")
        candidate = record["candidate"]
        fields(candidate, ("model_schema", "change_id", "component", "head", "base", "dirty", "categories", "inputs", "inputs_digest"), ("release",))
        schema(candidate)
        need(candidate["inputs_digest"] == digest(candidate["inputs"])
             and (candidate["change_id"], candidate["component"], candidate.get("release")) == (record["change_id"], record["component"], record.get("release"))
             and started.get("release") == record.get("release"),
             "HASH_MISMATCH", "Candidate manifest integrity mismatch")
        for index, result in enumerate(record["results"]):
            fields(result, ("id", "argv", "cwd", "acceptance_ids", "executed_by_roclec", "status", "returncode", "duration_seconds", "stdout", "stderr",
                            "environment"), ("limitation",))
            strings(result["acceptance_ids"])
            strings(result["environment"])
            for label in ("stdout", "stderr"):
                log = result[label]
                fields(log, ("path", "sha256", "size", "complete"), ("excerpt",))
                fingerprint(log["sha256"])
                need(log["path"] == f".roclec/runtime/logs/{run_id}/{index:03}.{label}"
                     and type(log["size"]) is int and log["size"] >= 0 and type(log["complete"]) is bool
                     and (result["status"] not in {"pass", "fail"} or log["complete"]),
                     "INVALID_INPUT", "Invalid local log descriptor", exit_code=2, entity=run_id)
                if "excerpt" in log:
                    need(isinstance(log["excerpt"], str) and len(log["excerpt"].encode("utf-8")) <= 1024 * 1024,
                         "INVALID_INPUT", "Invalid log excerpt", exit_code=2, entity=run_id)
        return record

    def log_issues(self, run):
        for result in run["results"]:
            for label in ("stdout", "stderr"):
                log = result[label]
                path = self.store.path(log["path"])
                if not path.is_file():
                    issue = ModelError("LOG_UNAVAILABLE", "Local capture is unavailable", path=log["path"], entity=run["id"]).issue
                    yield {**issue, "severity": "warning"}
                elif log["complete"]:
                    with path.open("rb") as stream:
                        actual = hashlib.file_digest(stream, "sha256").hexdigest()
                    need(actual == log["sha256"] and path.stat().st_size == log["size"],
                         "HASH_MISMATCH", "Local capture differs from its manifest", path=log["path"])

    def read_start(self, path):
        started = self.k.read(path.relative_to(self.k.profile.root).as_posix())
        fields(started, ("model_schema", "id", "change_id", "component", "candidate", "status", "checks", "digest",
                         "supersedes"), ("release", "producer"))
        need(started["id"] == path.parent.name and started["digest"] == digest({k: v for k, v in started.items() if k != "digest"}),
             "HASH_MISMATCH", "Run start integrity mismatch")
        identifier(started["id"], "RUN")
        need(started["component"] in self.k.profile.components and isinstance(started["checks"], list),
             "INVALID_REFERENCE", "Run start has an invalid component or check list")
        read_producer(started)
        if "release" in started:
            fields(started["release"], ("component", "version"))
            version_key(started["release"]["version"])
            need(started["change_id"] is None and started["release"]["component"] == started["component"],
                 "INVALID_REFERENCE", "Run start has an invalid release scope")
        else:
            identifier(started["change_id"], "CHG")
        return started

    def attempts(self, change_id, component):
        result = [started for started in (self.read_start(p) for p in self.store.path(".roclec/runs").glob("RUN-*/start.json"))
                  if self.same_scope(started, change_id, component)]
        return sorted(result, key=lambda r: r["id"])

    def record_evidence(self, file):
        record = read_json(file)
        fields(record, ("model_schema", "kind", "change_id", "component", "run_id", "candidate_digest", "actor", "context",
                        "outcome", "acceptance_ids", "checks", "limitations", "findings"), ("policy_id", "release", "role"))
        schema(record)
        need(record["kind"] in {"manual", "automated-import", "independent-review"}, "INVALID_INPUT", "Unknown evidence kind", exit_code=2)
        need(text(record["actor"]) and text(record["context"]), "INVALID_INPUT", "Declare observer and context", exit_code=2)
        review = record["kind"] == "independent-review"
        need(review or "role" not in record, "INVALID_INPUT", "Only an independent review declares a role", exit_code=2)
        if review:
            need("role" in record, "INVALID_INPUT", "An independent review must declare its role", exit_code=2,
                 expected=list(REVIEW_ROLES), remediation="Add role: " + " or ".join(REVIEW_ROLES))
            declared(record["role"], record["context"], REVIEW_ROLES, "review")
        for key in ("checks", "limitations"):
            need(isinstance(record[key], list) and all(text(s) for s in record[key]), "INVALID_INPUT", f"{key} must be strings", exit_code=2)
        need(isinstance(record["findings"], list), "INVALID_INPUT", "findings must be a list", exit_code=2)
        ids = []
        for finding in record["findings"]:
            fields(finding, ("id", "description"))
            need(text(finding["id"]) and text(finding["description"]), "INVALID_INPUT", "Findings need stable IDs and text", exit_code=2)
            ids.append(finding["id"])
        need(len(ids) == len(set(ids)), "ID_COLLISION", "Duplicate finding ID")
        need(record["outcome"] in ({"ready", "changes-needed", "incomplete"} if review else {"pass", "fail", "incomplete"}),
             "INVALID_INPUT", "Invalid evidence outcome", exit_code=2)
        run = self.read_run(record["run_id"])
        context = Verification(self.k, release=run.get("release"))
        need(context.same_scope(record, run["change_id"], run["component"]), "INVALID_REFERENCE", "Evidence scope differs from run")
        if review:
            need("producer" in run, "EVIDENCE_STALE", "The run has no declared producer context to review against",
                 entity=run["id"], remediation=RERUN_ATTRIBUTED)
            need(not same_context(record["context"], run["producer"]["context"]), "SELF_REVIEW_DECLARED",
                 "Review context equals the context that produced its run", entity=run["id"],
                 actual=record["context"], remediation=SEPARATE_CONTEXT)
        fingerprint(record["candidate_digest"])
        candidate = context.candidate(record["change_id"], record["component"], run["candidate"]["base"])
        need(record["candidate_digest"] == candidate["inputs_digest"] == run["candidate"]["inputs_digest"],
             "EVIDENCE_STALE", "Evidence must reference the current exact candidate")
        applicable = context.acceptance(context.target(record["change_id"]), record["component"])
        need(set(strings(record["acceptance_ids"])) <= set(applicable), "INVALID_REFERENCE", "Evidence cites an inapplicable AC")
        if review:
            policy = context.policy(record["change_id"])
            need(record.get("policy_id") == (policy["id"] if policy else None), "EVIDENCE_STALE", "Review policy changed")
            record["policy_id"] = policy["id"] if policy else None
        heads = scoped_heads(context.evidence(record["change_id"], record["component"]), self.report_scopes)
        supersedes = sorted({r["id"] for scope in self.report_scopes(record) for r in heads.get(scope, [])})
        record.update(id=record_id("EVD"), executed_by_roclec=False, supersedes=supersedes)
        record["digest"] = digest(record)
        receipt = self.store.apply("evidence-record", {"id": record["id"]},
                                   {f".roclec/evidence/{record['id']}.json": encoded(record)}, self.k.token)
        return {"evidence": record, "receipt": receipt}

    def read_evidence(self, path, runs=None):
        record = self.k.read(path.relative_to(self.k.profile.root).as_posix())
        fields(record, ("model_schema", "kind", "change_id", "component", "run_id", "candidate_digest", "actor", "context",
                        "outcome", "acceptance_ids", "checks", "limitations", "findings", "id", "digest", "executed_by_roclec",
                        "supersedes"), ("policy_id", "release", "role"))
        identifier(record["id"], "EVD")
        if "release" not in record:
            identifier(record["change_id"], "CHG")
        identifier(record["run_id"], "RUN")
        fingerprint(record["candidate_digest"])
        strings(record["acceptance_ids"])
        need(record["executed_by_roclec"] is False and record["kind"] in {"manual", "automated-import", "independent-review"}
             and record["component"] in self.k.profile.components and text(record["actor"]) and text(record["context"]),
             "INVALID_INPUT", "Invalid evidence attribution/scope", exit_code=2)
        need(record["outcome"] in ({"ready", "changes-needed", "incomplete"} if record["kind"] == "independent-review" else {"pass", "fail", "incomplete"}),
             "INVALID_INPUT", "Invalid evidence outcome", exit_code=2)
        need("role" not in record or (record["kind"] == "independent-review" and record["role"] in REVIEW_ROLES),
             "INVALID_INPUT", "Invalid evidence role", exit_code=2, entity=record["id"])
        for key in ("checks", "limitations"):
            need(isinstance(record[key], list) and all(text(v) for v in record[key]), "INVALID_INPUT", "Invalid observation strings", exit_code=2)
        need(record.get("id") == path.stem and record.get("digest") == digest({k: v for k, v in record.items() if k != "digest"}),
             "HASH_MISMATCH", "Evidence integrity mismatch")
        source = self.read_run(record["run_id"]) if runs is None else runs.get(record["run_id"])
        need(source is not None, "INVALID_REFERENCE", "Evidence requires a finalized run", entity=record["id"])
        need((source["change_id"], source["component"], source["candidate"]["inputs_digest"]) ==
             (record["change_id"], record["component"], record["candidate_digest"]),
             "INVALID_REFERENCE", "Evidence differs from its source run candidate")
        need(record.get("release") == source.get("release"), "INVALID_REFERENCE", "Evidence release scope differs from run")
        return record

    def evidence(self, change_id, component):
        records = [record for record in (self.read_evidence(p) for p in self.store.path(".roclec/evidence").glob("EVD-*.json"))
                   if self.same_scope(record, change_id, component)]
        return sorted(records, key=lambda r: r["id"])

    def verify(self, change_id, component, *, run_id=None, final=False):
        attempts = self.attempts(change_id, component)
        need(bool(attempts), "COVERAGE_MISSING", "No verification run for this component")
        latest = one_head(self.run_heads(attempts), "run")
        need(self.store.path(f".roclec/runs/{latest['id']}/manifest.json").is_file(), "CANDIDATE_INCOMPLETE",
             "Latest verification attempt was interrupted before finalization", entity=latest["id"])
        need(run_id is None or run_id == latest["id"], "EVIDENCE_STALE", "Use the latest verification attempt for this scope")
        run = self.read_run(latest["id"])
        need(self.same_scope(run, change_id, component), "INVALID_REFERENCE", "Run scope mismatch")
        candidate = self.candidate(change_id, component, run["candidate"]["base"], final=final)
        need(candidate["inputs_digest"] == run["candidate"]["inputs_digest"], "EVIDENCE_STALE", "Relevant candidate inputs changed")
        repo = self.k.profile.repo(component)
        need(git(repo, "merge-base", "--is-ancestor", run["candidate"]["head"], candidate["head"], check=False).returncode == 0,
             "EVIDENCE_STALE", "Current commit does not descend from the tested candidate")
        need(run["status"] == "pass", "CANDIDATE_INCOMPLETE", "Run did not pass", actual=run["status"])
        checks = self.k.profile.components[component]["verification"]
        need(len(run["results"]) == len(checks) and not run["limitations"] and all(r["status"] == "pass" and r["executed_by_roclec"] is True
             and type(r["returncode"]) is int and r["returncode"] == 0
             and r["acceptance_ids"] == c.get("acceptance_ids", [])
             and r["argv"] == c["argv"] and r["cwd"] == c["cwd"] and r["id"] == c["id"]
             for r, c in zip(run["results"], checks)), "CANDIDATE_INCOMPLETE", "Every declared check must have executed successfully")
        reports = self.evidence(change_id, component)
        heads = scoped_heads(reports, self.report_scopes)
        live = set()
        covered = {a for r in run["results"] for a in r["acceptance_ids"]}
        for ac in self.acceptance(self.target(change_id), component):
            report = one_head(heads, ("observation", ac))
            if not report or report["candidate_digest"] != candidate["inputs_digest"]:
                continue
            live.add(report["id"])
            if report["outcome"] == "pass" and report["checks"]:
                covered.add(ac)
            else:
                covered.discard(ac)
        missing = set(self.acceptance(self.target(change_id), component)) - covered
        need(not missing, "COVERAGE_MISSING", "Checks passing does not cover every applicable AC", actual=sorted(missing))
        policy = self.policy(change_id)
        if policy and policy["enabled"]:
            reviews = [one_head(heads, scope) for scope in sorted(heads) if scope[0] == "review"]
            current = [r for r in reviews if r["candidate_digest"] == candidate["inputs_digest"] and r.get("policy_id") == policy["id"]]
            # A review is compared with the run it cites and with the gated run.
            sources = {run["id"]: run}
            def producers(report):
                if report["run_id"] not in sources:
                    sources[report["run_id"]] = self.read_run(report["run_id"])
                return [sources[report["run_id"]].get("producer"), run.get("producer")]
            unattributed = [r for r in current if "role" not in r or None in producers(r)]
            accepted = [r for r in current if r not in unattributed]
            own = [r["id"] for r in accepted if any(same_context(r["context"], p["context"]) for p in producers(r))]
            need(not own, "SELF_REVIEW_DECLARED", "Review context equals the context that produced the reviewed run",
                 actual=own, remediation=SEPARATE_CONTEXT)
            need(any(r["outcome"] == "ready" and bool(r["checks"]) for r in accepted)
                 and all(r["outcome"] == "ready" for r in current),
                 "REVIEW_REQUIRED", "An enabled policy requires a current favorable independent report with no adverse current reviews",
                 actual=[r["id"] for r in unattributed] or None, remediation=RERUN_ATTRIBUTED if unattributed else None)
            live.update(r["id"] for r in accepted)
        return {"change": change_id, "component": component, "status": "verified", "run_id": run["id"],
                "candidate": candidate, "policy_id": policy["id"] if policy else None,
                "evidence": sorted(live), **self.extras()}
