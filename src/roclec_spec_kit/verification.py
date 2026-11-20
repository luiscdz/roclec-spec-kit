"""Candidate capture, executed checks and explicitly attributed observations.

Git is queried without a shell. Unknown/ignored paths are classified before any
content is read. Reports express claims; they cannot manufacture Roclec runs.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

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
        files, categories, unknown = {}, {}, []
        for relative in sorted(paths):
            # Operational records do not attest code or invalidate themselves.
            absolute = repo / relative
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
        return {"model_schema": 1, "change_id": change_id, "component": component,
                "head": head, "base": base_commit, "dirty": bool(status), "categories": categories,
                "inputs": inputs, "inputs_digest": digest(inputs), **self.extras()}

    def next_id(self, namespace, prefix):
        directory = self.store.path(f".roclec/{namespace}")
        ids = [int(p.name[len(prefix) + 1:].split('.')[0]) for p in directory.glob(f"{prefix}-*")
               if p.name[len(prefix) + 1:].split('.')[0].isdigit()]
        return f"{prefix}-{max(ids, default=0) + 1:03}"

    def run(self, change_id, component, base):
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
        run_id = self.next_id("runs", "RUN")
        root = f".roclec/runs/{run_id}"
        started = {"model_schema": 1, "id": run_id, "change_id": change_id, "component": component,
                   "candidate": before, "status": "incomplete", "checks": checks, **self.extras()}
        started["digest"] = digest(started)
        self.store.apply("run-start", {"id": run_id}, {f"{root}/start.json": encoded(started)}, self.k.token)
        execution_token = self.store.token()
        results, logs, interrupted = [], {}, False
        for check in checks:
            cwd = self.k.profile.repo(component) / check["cwd"]
            result = {"id": check["id"], "argv": check["argv"], "cwd": check["cwd"],
                      "acceptance_ids": check.get("acceptance_ids", []), "executed_by_roclec": False}
            start = time.monotonic()
            process = None
            out, err = b"", b""
            try:
                # A process group prevents a timeout/interrupt leaving children running.
                process = subprocess.Popen(check["argv"], cwd=cwd, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, start_new_session=True)
                result["executed_by_roclec"] = True
                out, err = process.communicate(timeout=check["timeout_seconds"])
                result.update(status="pass" if process.returncode == 0 else "fail", returncode=process.returncode)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                if process:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    out, err = process.communicate()
                interrupted = isinstance(exc, KeyboardInterrupt)
                result.update(status="interrupted" if interrupted else "incomplete", returncode=None,
                              limitation="interrupted" if interrupted else "timeout")
            except OSError as exc:
                result.update(status="incomplete", returncode=None, limitation=f"environment: {exc}")
            result["duration_seconds"] = round(time.monotonic() - start, 6)
            # Filenames are allocated by position, never by a consumer-controlled check id.
            index = len(results)
            for label, data in (("stdout", out), ("stderr", err)):
                relative = f"logs/{index:03}.{label}"
                logs[relative] = data
                result[label] = {"path": relative, "sha256": sha(data)}
            results.append(result)
            if interrupted:
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
        manifest = {"model_schema": 1, "id": run_id, "change_id": change_id, "component": component,
                    "candidate": before, "status": status, "results": results, "limitations": limitations,
                    "tools": before["inputs"]["tools"], **self.extras()}
        manifest["digest"] = digest(manifest)
        writes = {f"{root}/{p}": b for p, b in logs.items()}
        writes[f"{root}/manifest.json"] = encoded(manifest)
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

    def read_run(self, run_id):
        identifier(run_id, "RUN")
        record = self.k.read(f".roclec/runs/{run_id}/manifest.json")
        fields(record, ("model_schema", "id", "change_id", "component", "candidate", "status", "results", "limitations", "tools", "digest"), ("release",))
        need(record["id"] == run_id and record["digest"] == digest({k: v for k, v in record.items() if k != "digest"}),
             "HASH_MISMATCH", "Run manifest integrity mismatch")
        started = self.k.read(f".roclec/runs/{run_id}/start.json")
        need(started.get("digest") == digest({k: v for k, v in started.items() if k != "digest"})
             and all(started.get(k) == record[k] for k in ("id", "change_id", "component", "candidate")),
             "HASH_MISMATCH", "Run differs from its reserved candidate")
        need(record["status"] in {"pass", "fail", "incomplete", "interrupted"}
             and isinstance(record["results"], list) and isinstance(record["limitations"], list),
             "INVALID_INPUT", "Invalid run status/results", exit_code=2)
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
        for result in record["results"]:
            fields(result, ("id", "argv", "cwd", "acceptance_ids", "executed_by_roclec", "status", "returncode", "duration_seconds", "stdout", "stderr"), ("limitation",))
            strings(result["acceptance_ids"])
            for label in ("stdout", "stderr"):
                log = result[label]
                path = local_path(self.store.path(f".roclec/runs/{run_id}"), log["path"])
                need(path.is_file() and sha(path.read_bytes()) == log["sha256"], "HASH_MISMATCH", "Run log integrity mismatch")
        return record

    def attempts(self, change_id, component):
        result = []
        for path in self.store.path(".roclec/runs").glob("RUN-*/start.json"):
            started = self.k.read(path.relative_to(self.k.profile.root).as_posix())
            fields(started, ("model_schema", "id", "change_id", "component", "candidate", "status", "checks", "digest"), ("release",))
            need(started["id"] == path.parent.name and started["digest"] == digest({k: v for k, v in started.items() if k != "digest"}),
                 "HASH_MISMATCH", "Run start integrity mismatch")
            identifier(started["id"], "RUN")
            if self.same_scope(started, change_id, component):
                result.append(started)
        return sorted(result, key=lambda r: int(r["id"].split("-")[1]))

    def record_evidence(self, file):
        record = read_json(file)
        fields(record, ("model_schema", "kind", "change_id", "component", "run_id", "candidate_digest", "actor", "context",
                        "outcome", "acceptance_ids", "checks", "limitations", "findings"), ("policy_id", "release"))
        schema(record)
        need(record["kind"] in {"manual", "automated-import", "independent-review"}, "INVALID_INPUT", "Unknown evidence kind", exit_code=2)
        need(text(record["actor"]) and text(record["context"]), "INVALID_INPUT", "Declare observer and context", exit_code=2)
        for key in ("checks", "limitations"):
            need(isinstance(record[key], list) and all(text(s) for s in record[key]), "INVALID_INPUT", f"{key} must be strings", exit_code=2)
        need(isinstance(record["findings"], list), "INVALID_INPUT", "findings must be a list", exit_code=2)
        ids = []
        for finding in record["findings"]:
            fields(finding, ("id", "description"))
            need(text(finding["id"]) and text(finding["description"]), "INVALID_INPUT", "Findings need stable IDs and text", exit_code=2)
            ids.append(finding["id"])
        need(len(ids) == len(set(ids)), "ID_COLLISION", "Duplicate finding ID")
        review = record["kind"] == "independent-review"
        need(record["outcome"] in ({"ready", "changes-needed", "incomplete"} if review else {"pass", "fail", "incomplete"}),
             "INVALID_INPUT", "Invalid evidence outcome", exit_code=2)
        run = self.read_run(record["run_id"])
        context = Verification(self.k, release=run.get("release"))
        need(context.same_scope(record, run["change_id"], run["component"]), "INVALID_REFERENCE", "Evidence scope differs from run")
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
        record.update(id=self.next_id("evidence", "EVD"), executed_by_roclec=False)
        record["digest"] = digest(record)
        receipt = self.store.apply("evidence-record", {"id": record["id"]},
                                   {f".roclec/evidence/{record['id']}.json": encoded(record)}, self.k.token)
        return {"evidence": record, "receipt": receipt}

    def evidence(self, change_id, component):
        records = []
        for path in self.store.path(".roclec/evidence").glob("EVD-*.json"):
            record = self.k.read(path.relative_to(self.k.profile.root).as_posix())
            fields(record, ("model_schema", "kind", "change_id", "component", "run_id", "candidate_digest", "actor", "context",
                            "outcome", "acceptance_ids", "checks", "limitations", "findings", "id", "digest", "executed_by_roclec"), ("policy_id", "release"))
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
            for key in ("checks", "limitations"):
                need(isinstance(record[key], list) and all(text(v) for v in record[key]), "INVALID_INPUT", "Invalid observation strings", exit_code=2)
            need(record.get("id") == path.stem and record.get("digest") == digest({k: v for k, v in record.items() if k != "digest"}),
                 "HASH_MISMATCH", "Evidence integrity mismatch")
            source = self.read_run(record["run_id"])
            need((source["change_id"], source["component"], source["candidate"]["inputs_digest"]) ==
                 (record["change_id"], record["component"], record["candidate_digest"]),
                 "INVALID_REFERENCE", "Evidence differs from its source run candidate")
            need(record.get("release") == source.get("release"), "INVALID_REFERENCE", "Evidence release scope differs from run")
            if self.same_scope(record, change_id, component):
                records.append(record)
        return sorted(records, key=lambda r: int(r["id"].split("-")[1]))

    def verify(self, change_id, component, *, run_id=None, final=False):
        attempts = self.attempts(change_id, component)
        need(bool(attempts), "COVERAGE_MISSING", "No verification run for this component")
        latest = attempts[-1]
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
        live = [r for r in reports if r["candidate_digest"] == candidate["inputs_digest"]]
        covered = {a for r in run["results"] for a in r["acceptance_ids"]}
        observations = {}
        for report in live:
            if report["kind"] != "independent-review":
                for ac in report["acceptance_ids"]:
                    observations[ac] = report
        for ac, report in observations.items():
            if report["outcome"] == "pass" and report["checks"]:
                covered.add(ac)
            else:
                covered.discard(ac)
        missing = set(self.acceptance(self.target(change_id), component)) - covered
        need(not missing, "COVERAGE_MISSING", "Checks passing does not cover every applicable AC", actual=sorted(missing))
        policy = self.policy(change_id)
        if policy and policy["enabled"]:
            reviews = [r for r in reports if r["kind"] == "independent-review"]
            latest = reviews[-1] if reviews else None
            need(latest is not None and latest in live and latest.get("policy_id") == policy["id"]
                 and latest["outcome"] == "ready" and bool(latest["checks"]),
                 "REVIEW_REQUIRED", "An enabled policy requires a current favorable independent report")
        return {"change": change_id, "component": component, "status": "verified", "run_id": run["id"],
                "candidate": candidate, "policy_id": policy["id"] if policy else None,
                "evidence": [r["id"] for r in live], **self.extras()}
