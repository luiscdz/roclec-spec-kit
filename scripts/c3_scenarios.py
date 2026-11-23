"""Public C3 scenarios with real disposable Git remotes, never product publication."""
from __future__ import annotations

import json
from pathlib import Path

try:
    from .c1_scenarios import tree, bundle, criteria, declare_hook, snapshot, digest, put_json, adr_bundle, adr_caller, adr_markdown
    from .c2_scenarios import PRODUCER, setup, commit, git, prepared_fixture, finding, session_lifecycle
except ImportError:
    from c1_scenarios import tree, bundle, criteria, declare_hook, snapshot, digest, put_json, adr_bundle, adr_caller, adr_markdown
    from c2_scenarios import PRODUCER, setup, commit, git, prepared_fixture, finding, session_lifecycle


def scenarios(workspace, invoke, check):
    root, base = setup(workspace / "c3-publication", invoke)
    prefix = ["--project", str(root), "--json"]

    def call(label, *args, expect=0, issue=None, recorded=False):
        before = tree(root)
        result = invoke([*prefix, *map(str, args)])
        check(label, result.returncode == expect, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        check(label + ": JSON envelope", payload["ok"] == (expect == 0), result.stdout)
        if issue:
            check(label + ": issue", issue in [i["code"] for i in payload["issues"]], result.stdout)
        if expect in (1, 2, 3) and not recorded:
            check(label + ": rejection preserves bytes/modes", before == tree(root), result.stdout)
        return payload.get("data")

    run = call("C3 first component executes change checks", "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER)["run"]
    commit(root)
    plan = workspace / "c3-integration.json"
    call("C3 first component prepare integration", "integrate", "prepare", "CHG-001", "--component", "engine", "--run", run["id"], "--out", plan)
    call("C3 first component integrate", "operation", "apply", plan)
    call("I-031 unfinished participant cannot prepare", "run", "verify", "--release", "v1.0.0", "--component", "viewer", "--base", base, *PRODUCER, expect=1, issue="INVALID_REFERENCE")
    run = call("I-031 final combined release run", "run", "verify", "--release", "v1.0.0", "--component", "engine", "--base", base, *PRODUCER)["run"]
    check("Release run is distinct from change scope", run["change_id"] is None and run["release"] == {"component": "engine", "version": "v1.0.0"})
    release_scope = {"model_schema": 2, "change_id": None, "component": "engine", "release": run["release"]}
    policy = call("Inspect final release policy", "inspect", "--release", "v1.0.0", "--component", "engine")["review_policy"]
    report_file = workspace / "publication-observation.json"
    put_json(report_file, {**release_scope, "kind": "independent-review", "run_id": run["id"],
                           "candidate_digest": run["candidate"]["inputs_digest"], "policy_id": policy["id"],
                           "actor": "fixture reviewer", "context": "Synthetic reviewer session", "role": "reviewer",
                           "outcome": "ready", "acceptance_ids": ["AC-001"], "checks": ["Synthetic observation"],
                           "limitations": [], "findings": [finding("F-1", "info")], "resolutions": []})
    report = call("FH record a finding before publication", "evidence", "record", "--file", report_file)["evidence"]
    commit(root)
    call("C3 final release gate", "check", "--component", "engine", "--gate", "release", "--release", "v1.0.0")
    prepare_plan = workspace / "c3-release-prepare.json"
    prepared = call("I-030 export release preparation", "release", "prepare", "engine", "v1.0.0", "--run", run["id"], "--out", prepare_plan)["plan"]
    preparation = prepared["inputs"]["preparation"]
    shipped = prepared["inputs"]["candidate"]["head"]
    check("Export does not persist preparation", not (root / ".roclec/releases/engine/v1.0.0/preparations").exists())
    call("I-030 apply release preparation", "operation", "apply", prepare_plan)
    before = tree(root)
    call("C3 preparation repeat is idempotent", "operation", "apply", prepare_plan)
    check("Preparation repeat has no effects", before == tree(root))
    # Operational records are committed separately; the tag still identifies
    # the prepared shipped commit, not a metadata-only descendant.
    commit(root)
    remote = workspace / "c3-remote.git"
    remote.mkdir()
    git(remote, "init", "--bare", "-q")
    git(root, "remote", "add", "origin", str(remote))
    record_plan = workspace / "c3-release-record.json"
    def record(*, expect=0, issue=None):
        return call("I-030 record verified publication", "release", "record", "engine", "v1.0.0", "--preparation", preparation,
                    "--commit", shipped, "--tag", "v1.0.0", "--remote", "origin", "--actor", "fixture publisher",
                    "--reason", "Disposable Git harness publication", "--out", record_plan, expect=expect, issue=issue)
    record(expect=1, issue="TAG_MISMATCH")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "tag", "-a", "v1.0.0", shipped, "-m", "Synthetic annotated publication")
    record(expect=1, issue="TAG_MISMATCH")
    git(root, "push", "origin", "refs/tags/v1.0.0")
    exported = record()["plan"]
    query = exported["inputs"]["query"]
    check("I-030 annotated remote tag is peeled", query["refs"]["refs/tags/v1.0.0^{}"] == shipped)
    check("Export does not record publication", not (root / ".roclec/releases/engine/v1.0.0/publication.json").exists())
    call("I-031 apply actual Git publication record", "operation", "apply", record_plan)
    release = call("I-032 read frozen publication", "inspect", "--release", "v1.0.0", "--component", "engine")
    check("I-031 component publication independent", release["status"] == "published" and not (root / ".roclec/releases/viewer/v1.0.0/publication.json").exists())
    check("I-032 exact shipped candidate frozen", release["publication"]["commit"] == shipped and release["publication"]["evidence"]["preparation"] == preparation)
    release_member = release["record"]["changes"][0]
    frozen_source = root / ".roclec/changes/CHG-001/revisions" / release_member["intent_revision"] / "origins/request.md"
    check("FO published release retains the captured approved origin", frozen_source.read_text(encoding="utf-8")
          == "Synthetic request: present the agreed result.\n")
    call("I-032 published membership immutable", "release", "plan", "engine", "v1.0.0", "--clear", expect=1, issue="VERSION_INVALID")
    decision_file = workspace / "published-finding-decision.json"
    put_json(decision_file, {**release_scope, "kind": "finding-decision", "status": "accepted",
                             "findings": [report["id"] + "#F-1"], "actor": "fixture user",
                             "reason": "Attempt to change the published finding state"})
    call("FH published findings state is immutable", "evidence", "record", "--file", decision_file,
         expect=1, issue="VERSION_INVALID")
    call("FH published findings reject new review transitions", "evidence", "record", "--file", report_file,
         expect=1, issue="VERSION_INVALID")
    before = tree(root)
    call("C3 publication apply repeats without effects", "operation", "apply", record_plan)
    check("Historical publication receipt never rewrites records", before == tree(root))
    call("C3 completed consumer structurally valid", "check")
    return root, base, remote


def combined_and_fix_scenarios(workspace, invoke, check):
    root, base, remote = scenarios(workspace, invoke, check)
    prefix = ["--project", str(root), "--json"]

    def call(label, *args, expect=0, issue=None):
        before = tree(root)
        result = invoke([*prefix, *map(str, args)])
        check(label, result.returncode == expect, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        if issue:
            check(label + ": issue", issue in [i["code"] for i in payload["issues"]], result.stdout)
        if expect in (1, 2, 3):
            check(label + ": rejection preserves bytes/modes", before == tree(root), result.stdout)
        return payload.get("data")

    previous = snapshot()
    for number in (2, 3):
        target = snapshot(("engine",), ac=f"AC-{number:03}", behavior=f"evolution {number}")
        source = workspace / f"evolution-{number}"
        record = bundle(source, change_id=f"CHG-{number:03}", base=previous, target=target, components=("engine",))
        call("I-032 define later evolution", "change", "new", "--file", source / "change.json")
        call("I-032 approve later evolution", "change", "approve", record["id"], "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "Synthetic evolution",
             *criteria(root, "approve"))
        members = ["--change", "CHG-002"] + (["--change", "CHG-003"] if number == 3 else [])
        call("Combined release membership", "release", "plan", "engine", "v1.1.0", *members)
        config = root / ".roclec/project.toml"
        config.write_text(config.read_text().replace(f'acceptance_ids=["AC-{number-1:03}"]', f'acceptance_ids=["AC-{number:03}"]'))
        run = call("Execute evolved change checks", "run", "verify", record["id"], "--component", "engine", "--base", base, *PRODUCER)["run"]
        commit(root)
        plan = workspace / f"evolution-integration-{number}.json"
        call("Prepare later integration", "integrate", "prepare", record["id"], "--component", "engine", "--run", run["id"], "--out", plan)
        call("Apply later integration", "operation", "apply", plan)
        previous = target
    run = call("Combined release verifies final contract", "run", "verify", "--release", "v1.1.0", "--component", "engine", "--base", base, *PRODUCER)["run"]
    check("Superseded member criteria do not block final release", run["results"][0]["acceptance_ids"] == ["AC-003"]
          and len(run["candidate"]["inputs"]["release"]["contracts"]) == 1)
    commit(root)
    plan = workspace / "combined-preparation.json"
    preparation = call("Prepare combined release", "release", "prepare", "engine", "v1.1.0", "--run", run["id"], "--out", plan)["plan"]
    call("Persist combined preparation", "operation", "apply", plan)
    commit(root)
    shipped = preparation["inputs"]["candidate"]["head"]
    git(root, "tag", "v1.1.0", shipped)
    git(root, "push", "origin", "refs/tags/v1.1.0")
    plan = workspace / "combined-publication.json"
    call("Record combined publication", "release", "record", "engine", "v1.1.0", "--preparation", preparation["inputs"]["preparation"],
         "--commit", shipped, "--tag", "v1.1.0", "--remote", "origin", "--actor", "fixture", "--reason", "Synthetic combined release", "--out", plan)
    call("Persist combined publication", "operation", "apply", plan)
    old = call("I-032 historical contract remains exact", "inspect", "--capability", "CAP-001", "--component", "engine", "--at", "v1.0.0")
    check("I-032 old publication resolves original AC", old["components"]["engine"]["acceptance"][0]["id"] == "AC-001")
    call("I-029 evolution cannot enter a correction", "release", "plan", "engine", "v1.0.1", "--kind", "hotfix", "--base-tag", "v1.0.0", "--change", "CHG-003", expect=1, issue="VERSION_INVALID")
    # A local commit object on another ancestry, not a SHA-shaped placeholder.
    orphan = git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit-tree", "HEAD^{tree}", "-m", "unreachable implementation fixture")
    config = root / ".roclec/project.toml"
    config.write_text(config.read_text().replace('acceptance_ids=["AC-003"]', 'acceptance_ids=["AC-001"]'))
    # An actual included source change for the positive inclusion/backport cases.
    test = root / "src/check.py"
    test.write_text(test.read_text() + 'assert "saved" in __import__("pathlib").Path("src/value.txt").read_text()\n')
    included = commit(root)
    for number, reference, backport in ((4, "f" * 40, None), (5, orphan, None), (6, included, None),
                                          (7, orphan, {"commit": included})):
        change_id, version = f"CHG-{number:03}", f"v1.0.{number}"
        source = workspace / f"fix-{number}"
        record = bundle(source, change_id=change_id, base=snapshot(), components=("engine",), kind="fix")
        record["semantic"]["baseline_release"] = {"component": "engine", "version": "v1.0.0"}
        record["semantic"]["fixes"] = [{"component": "engine", "commit": reference, "requirement_ids": ["REQ-001"],
                                        "acceptance_ids": ["AC-001"], "backport": backport}]
        record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
        put_json(source / "change.json", record)
        call("I-028 define fix provenance", "change", "new", "--file", source / "change.json")
        call("I-028 approve fix provenance", "change", "approve", change_id, "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "Restore historical obligation",
             *criteria(root, "approve"))
        call("I-028 plan historical correction", "release", "plan", "engine", version, "--kind", "bugfix", "--base-tag", "v1.0.0", "--change", change_id)
        run = call("Execute historical fix checks", "run", "verify", change_id, "--component", "engine", "--base", base, *PRODUCER)["run"]
        commit(root)
        plan = workspace / f"fix-integration-{number}.json"
        call("Prepare historical fix integration", "integrate", "prepare", change_id, "--component", "engine", "--run", run["id"], "--out", plan)
        call("Integrate historical fix", "operation", "apply", plan)
        run = call("Verify historical correction release", "run", "verify", "--release", version, "--component", "engine", "--base", base, *PRODUCER)["run"]
        commit(root)
        plan = workspace / f"fix-preparation-{number}.json"
        if number in (4, 5, 7):
            call("I-028 nonexistent, excluded or unproven backport rejects", "release", "prepare", "engine", version, "--run", run["id"], "--out", plan,
                 expect=1, issue="FIX_NOT_INCLUDED")
        if number == 7:
            report = {"model_schema": 2, "kind": "manual", "change_id": None, "release": {"component": "engine", "version": version},
                      "component": "engine", "run_id": run["id"], "candidate_digest": run["candidate"]["inputs_digest"], "actor": "fixture observer",
                      "context": "Synthetic backport preservation observation", "outcome": "pass", "acceptance_ids": ["AC-001"],
                      "checks": ["Preservation of historical AC with the included backport"], "limitations": ["Structural fixture, no product acceptance"], "findings": []}
            file = workspace / "backport-evidence.json"
            put_json(file, report)
            evidence = call("I-028 record backport preservation", "evidence", "record", "--file", file)["evidence"]
            check("Explicit backport links real preservation record", evidence["id"].startswith("EVD-") and len(evidence["id"]) == 30)
            commit(root)
        if number in (6, 7):
            data = call("I-028 included implementation with preservation can prepare", "release", "prepare", "engine", version, "--run", run["id"], "--out", plan)
            check("Fix inclusion plan is reconstructible", data["plan"]["kind"] == "release-prepare")
    check("Historical fixes never rewind newer contracts", json.loads((root / ".roclec/current.json").read_text())["components"]["engine"]["CAP-001"] == previous["revision"])


def review_scenarios(workspace, invoke, check):
    root, base, integration = prepared_fixture(workspace / "release-review", invoke, member_finding=True)
    prefix = ["--project", str(root), "--json"]

    def call(label, *args, expect=0, issue=None, recorded=False):
        before = tree(root)
        result = invoke([*prefix, *map(str, args)])
        check(label, result.returncode == expect, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        if issue:
            check(label + ": issue", issue in [i["code"] for i in payload["issues"]], result.stdout)
        if expect in (1, 2, 3) and not recorded:
            check(label + ": rejection preserves bytes/modes", before == tree(root), result.stdout)
        if recorded:
            check(label + ": checks persisted before review", payload["data"]["recorded"] and payload["data"]["run"]["status"] == "pass")
        return payload.get("data")

    call("Release review fixture integrates", "operation", "apply", integration)
    call("Release adopts member's review policy", "review", "policy", "--change", "CHG-001", "--enabled", "true", "--actor", "fixture user", "--reason", "Review final release")
    run = call("D3 final release tests execute before review", "run", "verify", "--release", "v1.0.0", "--component", "engine", "--base", base, *PRODUCER,
               expect=1, issue="REVIEW_REQUIRED", recorded=True)["run"]
    commit(root)
    out = workspace / "review-preparation.json"
    call("D3 final release preparation rejects missing review", "release", "prepare", "engine", "v1.0.0", "--run", run["id"], "--out", out, expect=1, issue="REVIEW_REQUIRED")
    state = call("Inspect aggregate release review policy", "inspect", "--release", "v1.0.0", "--component", "engine")
    policy = state["review_policy"]
    check("Aggregate policy preserves explicit adoption provenance", policy["enabled"] and list(policy["members"]) == ["CHG-001"])
    check("M-28 release run records its declared producer", run["producer"] == {"role": "implementer", "context": "synthetic implementer session"})
    def review(actor, outcome, **changes):
        report = {"model_schema": 2, "kind": "independent-review", "change_id": None,
                  "release": {"component": "engine", "version": "v1.0.0"}, "component": "engine", "run_id": run["id"],
                  "candidate_digest": run["candidate"]["inputs_digest"], "policy_id": policy["id"], "actor": actor, "role": "reviewer",
                  "context": "Structural fixture; no actual independent human/model acceptance", "outcome": outcome, "acceptance_ids": ["AC-001"],
                  "checks": ["Synthetic observation of the final combined contract"], "limitations": ["No product acceptance"], "findings": [], "resolutions": []}
        file = workspace / "release-review.json"
        put_json(file, {**report, **changes})
        return file
    call("M-28 release self-review is rejected without writes", "evidence", "record", "--file",
         review("R1", "ready", context="SYNTHETIC implementer session"), expect=1, issue="SELF_REVIEW_DECLARED")
    for index, (actor, outcome) in enumerate((("R1", "ready"), ("R2", "changes-needed"), ("R1", "ready"),
                                               ("R2", "incomplete"), ("R2", "ready"))):
        call("Record final release " + outcome + " review", "evidence", "record", "--file", review(actor, outcome))
        commit(root)
        if index in (1, 2, 3):
            call("D3 unfavorable release review blocks preparation", "release", "prepare", "engine", "v1.0.0", "--run", run["id"], "--out", out, expect=1, issue="REVIEW_REQUIRED")
    past = call("FH member findings are visible in release queries", "list", "findings", "--change", "CHG-001")["findings"][0]
    introduced = call("FH favorable release review records findings", "evidence", "record", "--file",
                      review("R2", "ready", findings=[finding("F-1", "minor"), finding("F-2", "major"), finding("F-3", "info")]))["evidence"]
    commit(root)
    major = introduced["id"] + "#F-2"
    call("FH material release finding blocks preparation", "release", "prepare", "engine", "v1.0.0",
         "--run", run["id"], "--out", out, expect=1)
    fut_file = workspace / "release-fut.json"
    put_json(fut_file, {"model_schema": 2, "id": "FUT-001", "source": {"location": "docs/reference.md", "locator": "Fixture"},
                        "finding": "Follow-up", "impact": "Fixture only", "questions": []})
    call("FH capture release follow-up", "fut", "capture", "--file", fut_file)
    decision_file = workspace / "release-decision.json"
    deferred = introduced["id"] + "#F-3"
    for key, status, extra in ((major, "accepted", {}), (deferred, "deferred", {"fut_id": "FUT-001"})):
        put_json(decision_file, {"model_schema": 2, "kind": "finding-decision", "change_id": None,
                                 "component": "engine", "release": {"component": "engine", "version": "v1.0.0"},
                                 "status": status, "findings": [key], "actor": "fixture user",
                                 "reason": "User disposition of the synthetic finding", **extra})
        call("FH release disposition " + status, "evidence", "record", "--file", decision_file)
    commit(root)
    gate = call("FH release gate lists open, accepted and deferred", "check", "--gate", "release", "--release", "v1.0.0", "--component", "engine")
    listed = call("FH query includes member and release scopes", "list", "findings", "--release", "v1.0.0", "--component", "engine")["findings"]
    expected = {past["key"]: "open", introduced["id"] + "#F-1": "open", major: "accepted", deferred: "deferred"}
    check("FH release includes member and release findings", {row["key"]: row["status"] for row in listed} == expected, str(listed))
    check("FH final gate lists all dispositions", {row["key"]: row["status"] for row in gate["findings"]} == expected, str(gate))
    call("D3 current favorable release review permits preparation", "release", "prepare", "engine", "v1.0.0", "--run", run["id"], "--out", out)
    preparation = call("Persist release preparation with review", "operation", "apply", out)["preparation"]
    put_json(decision_file, {"model_schema": 2, "kind": "finding-decision", "change_id": None,
                             "component": "engine", "release": {"component": "engine", "version": "v1.0.0"},
                             "status": "accepted", "findings": [introduced["id"] + "#F-1"], "actor": "fixture user",
                             "reason": "Accept the remaining synthetic observation"})
    call("FH record changed disposition after preparation", "evidence", "record", "--file", decision_file)
    commit(root)
    call("FH publication rejects a preparation with different finding state", "release", "record", "engine", "v1.0.0",
         "--preparation", preparation, "--commit", "HEAD", "--tag", "v1.0.0", "--remote", "fixture",
         "--actor", "fixture user", "--reason", "Structural fixture", "--out", out, expect=1, issue="EVIDENCE_STALE")
    previous = list((root / ".roclec/releases/engine/v1.0.0/preparations").glob("*.json"))
    call("New adoption decision invalidates previous aggregate review", "review", "policy", "--change", "CHG-001", "--enabled", "true", "--actor", "fixture user", "--reason", "Fresh policy decision")
    commit(root)
    call("D3 old ready cannot satisfy changed release policy", "check", "--component", "engine", "--gate", "release", "--release", "v1.0.0", expect=1, issue="REVIEW_REQUIRED")
    call("D3 user disables participation with reason", "review", "policy", "--change", "CHG-001", "--enabled", "false", "--actor", "fixture user", "--reason", "End fixture participation")
    commit(root)
    call("D3 disabled release review allows gate", "check", "--component", "engine", "--gate", "release", "--release", "v1.0.0")
    check("D3 old preparations/reports remain historical", all(p.exists() for p in previous) and len(list((root / ".roclec/evidence").glob("*.json"))) == 10)


def adr_scenarios(workspace, invoke, check):
    """A member citing a later-superseded ADR is reported by the release gate, which still prepares and applies."""
    root, base = setup(workspace / "c3-adr", invoke, names=("engine",))
    call = adr_caller(root, invoke, check)

    def register(adr_id, *supersedes):
        path = root / "docs/adr" / f"{adr_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(adr_markdown(f"{adr_id}: Decision"), encoding="utf-8")
        args = ["reference", "add", adr_id, "--path", f"docs/adr/{adr_id}.md", "--component", "engine", "--role", "decision"]
        for older in supersedes:
            args += ["--supersedes", older]
        call(f"C3 ADR register {adr_id}", *args)
        call(f"C3 ADR agree {adr_id}", "foundation", "agree", "--ref", adr_id, "--actor", "Maintainer", "--reason", "Accepted ADR",
             *criteria(root, "foundation"))

    def integrate(change_id):
        run = call(f"C3 ADR verify {change_id}", "run", "verify", change_id, "--component", "engine", "--base", base, *PRODUCER)["data"]["run"]
        commit(root)
        plan = workspace / f"c3-adr-{change_id}.json"
        call(f"C3 ADR prepare {change_id}", "integrate", "prepare", change_id, "--component", "engine", "--run", run["id"], "--out", plan)
        call(f"C3 ADR apply {change_id}", "operation", "apply", plan)

    register("ADR-001")
    commit(root)
    integrate("CHG-001")
    folder = adr_bundle(workspace / "c3-adr-bundle", "CHG-002", {"adrs": [{"id": "ADR-001"}]}, base=snapshot(("engine",)))
    call("C3 ADR seal citing change", "change", "seal", folder)
    call("C3 ADR new citing change", "change", "new", "--file", folder / "change.json")
    record = json.loads((folder / "change.json").read_text())
    call("C3 ADR approve citing change", "change", "approve", "CHG-002", "--digest", record["proposal_digest"],
         "--actor", "fixture", "--reason", "Approved scope", *criteria(root, "approve"))
    call("C3 ADR release membership", "release", "plan", "engine", "v1.0.0", "--change", "CHG-001", "--change", "CHG-002")
    commit(root)
    integrate("CHG-002")
    register("ADR-002", "ADR-001")
    commit(root)
    run = call("C3 ADR final release run", "run", "verify", "--release", "v1.0.0", "--component", "engine", "--base", base, *PRODUCER)["data"]["run"]
    policy = call("C3 ADR inspect final review policy", "inspect", "--release", "v1.0.0", "--component", "engine")["data"]["review_policy"]
    report = workspace / "c3-adr-review.json"
    put_json(report, {"model_schema": 2, "kind": "independent-review", "change_id": None, "component": "engine",
                      "release": run["release"], "run_id": run["id"], "candidate_digest": run["candidate"]["inputs_digest"],
                      "policy_id": policy["id"], "actor": "Fixture reviewer", "role": "reviewer", "context": "C3 review fixture",
                      "outcome": "ready", "acceptance_ids": [], "checks": ["Observed synthetic behavior"], "limitations": [],
                      "findings": [{**finding("F-1", "minor"), "acceptance_ids": []}], "resolutions": []})
    evidence = call("C3 FH record a nonmaterial release finding", "evidence", "record", "--file", report)["data"]["evidence"]
    commit(root)
    gate = call("C3 ADR and FH release limitations do not block", "check", "--component", "engine", "--gate", "release", "--release", "v1.0.0")["data"]
    check("C3 release gate reports open findings and superseded ADRs as objects", gate["limitations"] == [
        {"code": "FINDING_OPEN", "key": evidence["id"] + "#F-1"},
        {"code": "ADR_SUPERSEDED", "change_id": "CHG-002", "adr": "ADR-001", "superseded_by": ["ADR-002"]}], str(gate.get("limitations")))
    out = workspace / "c3-adr-release.json"
    plan = call("C3 ADR release prepare still works", "release", "prepare", "engine", "v1.0.0", "--run", run["id"], "--out", out)["data"]["plan"]
    call("C3 ADR release preparation applies", "operation", "apply", out)
    stored = list((root / ".roclec/releases/engine/v1.0.0/preparations").glob("*.json"))
    check("C3 ADR preparation is persisted", len(stored) == 1 and plan["inputs"]["preparation"], "")


def hook_scenarios(workspace, invoke, check):
    """FF hooks with real runs, Git integration and release preparation on one component.

    pre-implement declares no criteria, pre-integrate and handoff declare one each. Every
    declared hook blocks its gate until a human checkpoint approves the exact subject digest.
    """
    root, base = setup(workspace / "c3-hooks", invoke, names=("engine",))
    call = adr_caller(root, invoke, check)
    actor = ("--actor", "Fixture owner", "--reason", "Synthetic human decision")
    declare_hook(root, "pre-implement")
    declare_hook(root, "pre-integrate", declared={"CR-007": "The tested candidate is the one to integrate."})
    declare_hook(root, "handoff", declared={"CR-008": "QA can take the integrated change."}, on_reject="defer")
    call("FF hooks agree the edited flow", "foundation", "agree", "--ref", "flow", *actor, *criteria(root, "foundation"))
    call("FF hooks regenerate the flow view", "views", "--write")
    commit(root)
    change = json.loads((root / ".roclec/changes/CHG-001/change.json").read_text())
    proposal = change["proposal_digest"]

    def hook(label, name, subject, *extra, change="CHG-001", expect=0, issue=None):
        return call(label, "checkpoint", change, "--hook", name, "--component", "engine", "--digest", subject, *actor,
                    *extra, expect=expect, issue=issue)

    blocked = call("FF pre-implement blocks the implement gate", "check", "--change", "CHG-001", "--component", "engine",
                   "--gate", "implement", expect=1, issue="CHECKPOINT_REQUIRED")["issues"][0]
    check("FF pre-implement names the proposal digest and the exact command",
          blocked["expected"] == proposal and blocked["entity"] == "CHG-001/engine/pre-implement"
          and f"roclec checkpoint CHG-001 --hook pre-implement --component engine --digest {proposal}" in blocked["remediation"],
          str(blocked))
    data = call("FF conformance with a pending pre-implement decision", "inspect", "--change", "CHG-001")["data"]
    stages = conformance(data)
    check("FF conformance pins the current flow and the flow the approval was given under",
          data["flow"]["sha256"] == file_sha(root / ".roclec/flow.toml") and data["flow"]["agreed"] is True
          and data["flow"]["approved_under"] == data["approval"]["flow"] != data["flow"]["sha256"], str(data["flow"]))
    approve = stages["approve"]
    check("FF conformance shows the approval actor and its evaluated criteria",
          approve["ai"] is False and "cannot prove" in approve["limitation"]
          and approve["change"]["status"] == "done" and approve["change"]["record"] == data["approval"]["id"]
          and approve["change"]["actor"] == "fixture" and approve["change"]["criteria"] == data["approval"]["criteria"],
          str(approve))
    pending = stages["implement"]["components"]["engine"]["hook"]
    check("FF conformance shows the pending pre-implement point with its decider",
          pending == {"status": "pending", "record": None, "actor": None, "criteria": [], "name": "pre-implement",
                      "subject": proposal, "pending": {"decider": "owner", "criteria": []}}, str(pending))
    check("FF conformance shows the release assignment", stages["plan"]["components"]["engine"]["record"] == "engine/v1.0.0",
          str(stages["plan"]))
    call("FF pre-implement blocks runs", "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER,
         expect=1, issue="CHECKPOINT_REQUIRED")
    hook("FF pre-implement rejects a stale digest", "pre-implement", "0" * 64, "--outcome", "approved",
         expect=1, issue="APPROVAL_STALE")
    hook("FF pre-implement takes no run", "pre-implement", proposal, "--outcome", "approved", "--run", "RUN-x",
         expect=2, issue="INVALID_INPUT")
    approved = hook("FF pre-implement approval without criteria", "pre-implement", proposal, "--outcome", "approved")["data"]
    check("FF hook decision records its subject, empty criteria and flow pin",
          approved["decision"]["subject"] == {"type": "stage", "entity": "CHG-001", "digest": proposal}
          and approved["decision"]["criteria"] == [] and approved["decision"]["flow"] == file_sha(root / ".roclec/flow.toml"),
          str(approved))
    first = call("FF approved pre-implement permits the run", "run", "verify", "CHG-001", "--component", "engine",
                 "--base", base, *PRODUCER)["data"]["run"]
    commit(root)
    plan = workspace / "c3-hooks-integration.json"
    blocked = call("FF pre-integrate blocks integration", "integrate", "prepare", "CHG-001", "--component", "engine",
                   "--run", first["id"], "--out", plan, expect=1, issue="CHECKPOINT_REQUIRED")["issues"][0]
    check("FF pre-integrate names the run candidate", blocked["expected"] == first["candidate"]["inputs_digest"]
          and f"--run {first['id']}" in blocked["remediation"] and "CR-007" in blocked["remediation"], str(blocked))
    stages = conformance(call("FF conformance with a pending pre-integrate decision", "inspect", "--change", "CHG-001")["data"])
    pending = stages["integrate"]["components"]["engine"]
    check("FF conformance presents the pending pre-integrate criteria with their text",
          pending["status"] == "pending" and pending["hook"]["status"] == "pending"
          and pending["hook"]["subject"] == first["candidate"]["inputs_digest"]
          and pending["hook"]["pending"] == {"decider": "owner", "criteria": [
              {"id": "CR-007", "text": "The tested candidate is the one to integrate."}]}, str(pending))
    implemented = stages["implement"]["components"]["engine"]
    check("FF conformance records the pre-implement decision and the run",
          implemented["hook"]["status"] == "done" and implemented["hook"]["record"] == approved["decision"]["id"]
          and implemented["hook"]["actor"] == "Fixture owner" and implemented["record"] == first["id"]
          and stages["verify"]["components"]["engine"]["record"] == first["id"], str(implemented))
    call("FF pre-integrate blocks the integrate gate", "check", "--change", "CHG-001", "--component", "engine",
         "--gate", "integrate", expect=1, issue="CHECKPOINT_REQUIRED")
    hook("FF pre-integrate needs its run", "pre-integrate", first["candidate"]["inputs_digest"], "--outcome", "approved",
         *criteria(root, "pre-integrate"), expect=2, issue="INVALID_INPUT")
    hook("FF pre-integrate rejects another digest", "pre-integrate", proposal, "--run", first["id"], "--outcome", "approved",
         *criteria(root, "pre-integrate"), expect=1, issue="APPROVAL_STALE")
    corrections = workspace / "c3-hooks-corrections.json"
    put_json(corrections, [{"id": "R-1", "description": "Cover the empty value"}])
    rejection = hook("FF pre-integrate rejection defaults to revise", "pre-integrate", first["candidate"]["inputs_digest"],
                     "--run", first["id"], "--outcome", "rejected", "--corrections", corrections,
                     *criteria(root, "pre-integrate", "rejected"))["data"]["decision"]
    hook_state = conformance(call("FF conformance after the pre-integrate rejection", "inspect", "--change",
                                  "CHG-001")["data"])["integrate"]["components"]["engine"]["hook"]
    check("FF conformance shows the rejected pre-integrate point as blocked",
          hook_state["status"] == "blocked" and hook_state["record"] == rejection["id"]
          and hook_state["criteria"] == rejection["criteria"], str(hook_state))
    check("FF stage rejection keeps corrections and consequence", rejection["consequence"] == "revise"
          and rejection["corrections"][0]["id"] == "R-1" and rejection["criteria"][0]["status"] == "not-met", str(rejection))
    commit(root)
    hook("FF rejected candidate cannot be approved again", "pre-integrate", first["candidate"]["inputs_digest"],
         "--run", first["id"], "--outcome", "approved", *criteria(root, "pre-integrate"), expect=1, issue="REJECTION_UNRESOLVED")
    check_file = root / "src/check.py"
    check_file.write_text(check_file.read_text() + "# Cover the empty value as requested.\n")
    commit(root)
    second = call("FF revised candidate run", "run", "verify", "CHG-001", "--component", "engine", "--base", base,
                  *PRODUCER)["data"]["run"]
    commit(root)
    check("FF revised candidate has another digest", second["candidate"]["inputs_digest"] != first["candidate"]["inputs_digest"])
    call("FF the revised candidate needs its own approval", "integrate", "prepare", "CHG-001", "--component", "engine",
         "--run", second["id"], "--out", plan, expect=1, issue="CHECKPOINT_REQUIRED")
    hook("FF re-approval needs the corrections", "pre-integrate", second["candidate"]["inputs_digest"], "--run", second["id"],
         "--outcome", "approved", *criteria(root, "pre-integrate"), expect=1, issue="CORRECTIONS_REQUIRED")
    responses = workspace / "c3-hooks-addresses.json"
    put_json(responses, {"rejection": rejection["id"], "corrections": [{"id": "R-1", "status": "addressed"}]})
    hook("FF re-approval of the new candidate addresses the rejection", "pre-integrate", second["candidate"]["inputs_digest"],
         "--run", second["id"], "--outcome", "approved", "--addresses", responses, *criteria(root, "pre-integrate"))
    check("FF addressed stage rejection is closed",
          not call("FF open rejections", "list", "rejections", "--open")["data"]["rejections"])
    commit(root)
    # Review regression: an approval of earlier bytes cannot bypass a later revise rejection.
    approved_source = check_file.read_bytes()
    check_file.write_text(check_file.read_text() + "# Experimental variant.\n")
    commit(root)
    third = call("FF variant candidate run", "run", "verify", "CHG-001", "--component", "engine", "--base", base,
                 *PRODUCER)["data"]["run"]
    commit(root)
    variant = hook("FF variant candidate rejected for revision", "pre-integrate", third["candidate"]["inputs_digest"],
                   "--run", third["id"], "--outcome", "rejected", "--corrections", corrections,
                   *criteria(root, "pre-integrate", "rejected"))["data"]["decision"]
    check_file.write_bytes(approved_source)
    commit(root)
    fourth = call("FF restored candidate run", "run", "verify", "CHG-001", "--component", "engine", "--base", base,
                  *PRODUCER)["data"]["run"]
    commit(root)
    check("FF restored candidate repeats the approved digest",
          fourth["candidate"]["inputs_digest"] == second["candidate"]["inputs_digest"])
    blocked = call("FF earlier approval does not bypass the later rejection", "integrate", "prepare", "CHG-001",
                   "--component", "engine", "--run", fourth["id"], "--out", plan, expect=1, issue="CHECKPOINT_REQUIRED")
    check("FF bypass attempt reports the stale approval", blocked["issues"][0]["actual"] == "approved", str(blocked))
    call("FF earlier approval does not satisfy the integrate gate", "check", "--change", "CHG-001", "--component", "engine",
         "--gate", "integrate", expect=1, issue="CHECKPOINT_REQUIRED")
    put_json(responses, {"rejection": variant["id"], "corrections": [{"id": "R-1", "status": "addressed"}]})
    hook("FF restored candidate approved again, addressing the variant rejection", "pre-integrate",
         fourth["candidate"]["inputs_digest"], "--run", fourth["id"], "--outcome", "approved", "--addresses", responses,
         *criteria(root, "pre-integrate"))
    commit(root)
    call("FF approved pre-integrate passes the integrate gate", "check", "--change", "CHG-001", "--component", "engine",
         "--gate", "integrate")
    call("FF approved pre-integrate permits integration", "integrate", "prepare", "CHG-001", "--component", "engine",
         "--run", fourth["id"], "--out", plan)
    call("FF integration applies", "operation", "apply", plan)
    commit(root)
    integration = call("FF integrated change", "inspect", "--change", "CHG-001")["data"]["integrations"]["engine"]

    # A second member of v1.0.0, a preservation change, goes through the same hooks.
    second_change = bundle(workspace / "c3-hooks-second", change_id="CHG-002", base=snapshot(("engine",)),
                           components=("engine",), kind="refactor")
    call("FF second member imported", "change", "new", "--file", workspace / "c3-hooks-second/change.json")
    call("FF second member approved", "change", "approve", "CHG-002", "--digest", second_change["proposal_digest"], *actor,
         *criteria(root, "approve"))
    call("FF second member planned", "release", "plan", "engine", "v1.0.0", "--change", "CHG-001", "--change", "CHG-002")
    hook("FF second member pre-implement", "pre-implement", second_change["proposal_digest"], "--outcome", "approved",
         change="CHG-002")
    commit(root)
    run = call("FF second member run", "run", "verify", "CHG-002", "--component", "engine", "--base", base,
               *PRODUCER)["data"]["run"]
    commit(root)
    hook("FF second member pre-integrate", "pre-integrate", run["candidate"]["inputs_digest"], "--run", run["id"],
         "--outcome", "approved", *criteria(root, "pre-integrate"), change="CHG-002")
    commit(root)
    second_plan = workspace / "c3-hooks-second-integration.json"
    call("FF second member integration prepared", "integrate", "prepare", "CHG-002", "--component", "engine",
         "--run", run["id"], "--out", second_plan)
    call("FF second member integrated", "operation", "apply", second_plan)
    commit(root)
    second_integration = call("FF second member inspected", "inspect", "--change", "CHG-002")["data"]["integrations"]["engine"]
    release = call("FF final release run", "run", "verify", "--release", "v1.0.0", "--component", "engine", "--base", base,
                   *PRODUCER)["data"]["run"]
    commit(root)
    out = workspace / "c3-hooks-release.json"

    # The release gate reads hooks only from the agreed flow.
    agreed = (root / ".roclec/flow.toml").read_bytes()
    (root / ".roclec/flow.toml").write_bytes(agreed.replace(b"Approve the exact intent", b"Approve the full intent"))
    unagreed = call("FF unagreed flow blocks the release gate", "check", "--component", "engine", "--gate", "release",
                    "--release", "v1.0.0", expect=1, issue="FOUNDATION_INCOMPLETE")["issues"][0]
    check("FF unagreed flow remediation asks for agreement", "foundation agree --ref flow" in unagreed["remediation"], str(unagreed))
    call("FF unagreed flow blocks release preparation", "release", "prepare", "engine", "v1.0.0", "--run", release["id"],
         "--out", out, expect=1, issue="FOUNDATION_INCOMPLETE")
    (root / ".roclec/flow.toml").write_bytes(agreed)

    blocked = call("FF handoff blocks the release gate", "check", "--component", "engine", "--gate", "release",
                   "--release", "v1.0.0", expect=1, issue="CHECKPOINT_REQUIRED")["issues"][0]
    check("FF handoff names the integration record", blocked["expected"] == integration["digest"]
          and blocked["entity"] == "CHG-001/engine/handoff", str(blocked))
    call("FF handoff blocks release preparation", "release", "prepare", "engine", "v1.0.0", "--run", release["id"],
         "--out", out, expect=1, issue="CHECKPOINT_REQUIRED")
    for consequence in ("revise", "cancel"):
        refused = hook(f"FF handoff refuses {consequence}", "handoff", integration["digest"], "--outcome", "rejected",
                       "--consequence", consequence, "--corrections", corrections, *criteria(root, "handoff", "rejected"),
                       expect=2, issue="INVALID_INPUT")["issues"][0]
        check(f"FF handoff {consequence} remediation points to defer", "--consequence defer" in refused["remediation"], str(refused))
    hook("FF handoff default defer needs a FUT", "handoff", integration["digest"], "--outcome", "rejected",
         "--corrections", corrections, *criteria(root, "handoff", "rejected"), expect=2, issue="INVALID_INPUT")
    for number in (1, 2):
        fut = workspace / f"c3-hooks-fut-{number}.json"
        put_json(fut, {"model_schema": 2, "id": f"FUT-00{number}", "source": {"location": "docs/reference.md", "locator": "Fixture"},
                       "finding": "QA follow-up fix", "impact": "Fixture only", "questions": []})
        call(f"FF capture follow-up {number}", "fut", "capture", "--file", fut)
    deferred = hook("FF handoff rejection defers to a FUT", "handoff", integration["digest"], "--outcome", "rejected",
                    "--corrections", corrections, "--fut", "FUT-001", *criteria(root, "handoff", "rejected"))["data"]["decision"]
    check("FF default consequence comes from the flow", deferred["consequence"] == "defer" and deferred["fut"] == "FUT-001", str(deferred))
    handoff = conformance(call("FF conformance after the deferred handoff", "inspect", "--change",
                               "CHG-001")["data"])["release"]["components"]["engine"]["hook"]
    check("FF conformance shows the deferred handoff as blocked",
          handoff["status"] == "blocked" and handoff["record"] == deferred["id"] and handoff["consequence"] == "defer",
          str(handoff))
    commit(root)
    call("FF deferred handoff still blocks preparation", "release", "prepare", "engine", "v1.0.0", "--run", release["id"],
         "--out", out, expect=1, issue="CHECKPOINT_REQUIRED")
    hook("FF handoff approval of the same integration after defer", "handoff", integration["digest"], "--outcome", "approved",
         *criteria(root, "handoff"))
    commit(root)
    blocked = call("FF second member still needs its handoff", "check", "--component", "engine", "--gate", "release",
                   "--release", "v1.0.0", expect=1, issue="CHECKPOINT_REQUIRED")["issues"][0]
    check("FF second member handoff names its record", blocked["entity"] == "CHG-002/engine/handoff"
          and blocked["expected"] == second_integration["digest"], str(blocked))
    call("FF integrated member cannot leave the release without a deferred handoff", "release", "plan", "engine", "v1.0.0",
         "--change", "CHG-001", expect=1, issue="CHANGE_IN_PROGRESS")
    hook("FF second member deferred at handoff", "handoff", second_integration["digest"], "--outcome", "rejected",
         "--corrections", corrections, "--fut", "FUT-002", *criteria(root, "handoff", "rejected"), change="CHG-002")
    commit(root)
    plan_data = call("FF deferred member leaves the planning release", "release", "plan", "engine", "v1.0.0", "--change", "CHG-001")["data"]
    check("FF release keeps only the remaining member", [m["change_id"] for m in plan_data["release"]["changes"]] == ["CHG-001"],
          str(plan_data))
    commit(root)
    release = call("FF release run for the remaining member", "run", "verify", "--release", "v1.0.0", "--component", "engine",
                   "--base", base, *PRODUCER)["data"]["run"]
    commit(root)
    call("FF approved handoff passes the release gate", "check", "--component", "engine", "--gate", "release", "--release", "v1.0.0")
    call("FF approved handoff permits release preparation", "release", "prepare", "engine", "v1.0.0", "--run", release["id"],
         "--out", out)
    call("FF release preparation applies", "operation", "apply", out)
    call("FF hook history is structurally valid", "check")
    first_view = call("FF conformance of the integrated change", "inspect", "--change", "CHG-001")["data"]
    again = call("FF conformance read twice", "inspect", "--change", "CHG-001")["data"]
    check("FF conformance is deterministic", first_view["flow"] == again["flow"])
    stages = conformance(first_view)
    check("FF conformance lists every canonical stage in order",
          list(stages) == ["foundation", "define", "approve", "design", "plan", "implement", "verify", "review",
                           "integrate", "release"], str(list(stages)))
    engine = {name: (row["change"] if "change" in row else row["components"]["engine"]) for name, row in stages.items()}
    expected = {"foundation": ("done", first_view["flow"]["stages"][0]["components"]["engine"]["record"]),
                "define": ("done", first_view["change"]["proposal_digest"]),
                "approve": ("done", first_view["approval"]["id"]),
                "design": ("n/a", None), "plan": ("done", "engine/v1.0.0"),
                "implement": ("done", first["id"]), "verify": ("done", fourth["id"]),
                "review": ("n/a", None), "integrate": ("done", integration["digest"]),
                "release": ("pending", None)}
    check("FF integrated change shows each stage's record",
          {name: (row["status"], row["record"]) for name, row in engine.items()} == expected
          and engine["foundation"]["record"] is not None, json.dumps(engine, sort_keys=True))
    check("FF integrated change shows each decided hook",
          [engine[name]["hook"]["status"] for name in ("implement", "integrate", "release")] == ["done"] * 3
          and engine["release"]["hook"]["criteria"] == [{"id": "CR-008", "status": "met"}]
          and engine["release"]["releases"] == [{"version": "v1.0.0", "status": "planning", "publication": None}],
          json.dumps(engine, sort_keys=True))
    second_stages = conformance(call("FF conformance of the deferred member", "inspect", "--change", "CHG-002")["data"])
    check("FF deferred member left the release and keeps its blocked handoff",
          second_stages["plan"]["components"]["engine"]["status"] == "pending"
          and second_stages["release"]["components"]["engine"]["hook"]["status"] == "blocked",
          str(second_stages["release"]))
    return root


def conformance(data):
    """Stages of the `inspect --change` flow section by name."""
    return {row["stage"]: row for row in data["flow"]["stages"]}


def file_sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def session_release_scenarios(workspace, invoke, check):
    """FL `release record` demands a release session when the seeded flow requires one, with a real disposable remote."""
    state = session_lifecycle(workspace / "c3-sessions", invoke, check)
    root, call, record, run = state["root"], state["call"], state["record"], state["run"]
    workspace = state["workspace"]
    prepare_plan = workspace / "release-prepare.json"
    prepared = call("FL C3 export release preparation", "release", "prepare", "engine", "v1.0.0", "--run", run["id"],
                    "--out", prepare_plan)["data"]["plan"]
    preparation, shipped = prepared["inputs"]["preparation"], prepared["inputs"]["candidate"]["head"]
    call("FL C3 apply release preparation", "operation", "apply", prepare_plan)
    commit(root)
    remote = workspace / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare", "-q")
    git(root, "remote", "add", "origin", str(remote))
    record_plan = workspace / "release-record.json"
    publish = ("release", "record", "engine", "v1.0.0", "--preparation", preparation, "--commit", shipped, "--tag", "v1.0.0",
               "--remote", "origin", "--actor", "fixture publisher", "--reason", "Disposable Git harness publication",
               "--out", record_plan)
    issue = call("FL C3 release record demands the release session", *publish, expect=1, issue="SESSION_REQUIRED")["issues"][0]
    check("FL C3 the demand names the release", issue["expected"] == "release" and issue["entity"] == "engine/v1.0.0"
          and "evidence record --kind agent-session" in issue["remediation"], str(issue))
    check("FL C3 the rejected record exports no plan", not record_plan.exists(), "")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "tag", "-a", "v1.0.0", shipped,
        "-m", "Synthetic annotated publication")
    git(root, "push", "origin", "refs/tags/v1.0.0")
    call("FL C3 a session of another release does not count", "evidence", "record", "--kind", "agent-session", "--file",
         _release_meta(workspace, "v9.0.0"), "--transcript", _release_transcript(workspace), expect=2, issue="INVALID_REFERENCE")
    record("FL C3 import the release session", "release", "coordinator", release={"component": "engine", "version": "v1.0.0"})
    commit(root)
    exported = call("FL C3 release record passes with the release session", *publish)["data"]["plan"]
    check("FL C3 the exported plan names the prepared commit", exported["inputs"]["query"]["refs"]["refs/tags/v1.0.0^{}"] == shipped, "")
    call("FL C3 apply the publication record", "operation", "apply", record_plan)
    published = call("FL C3 inspect the publication", "inspect", "--release", "v1.0.0", "--component", "engine")["data"]
    check("FL C3 publication freezes the prepared commit", published["status"] == "published"
          and published["publication"]["commit"] == shipped, str(published["status"]))
    check("FL C3 the published consumer is clean", [i for i in call("FL C3 final check", "check")["issues"]
                                                   if i["code"] not in {"FLOW_VIEW_STALE", "SESSION_REDACTION_EMPTY"}] == [], "")


def _release_meta(workspace, version):
    path = workspace / "inputs" / "other-release.json"
    put_json(path, {"model_schema": 2, "host": "claude-code", "host_session_id": "other-release", "actor": "Fixture agent",
                    "role": "coordinator", "model": "fixture-model", "started_at": "2026-01-31T09:00:00Z",
                    "ended_at": "2026-01-31T09:30:00Z", "stage": "release",
                    "release": {"component": "engine", "version": version}})
    return path


def _release_transcript(workspace):
    path = workspace / "inputs" / "other-release.jsonl"
    path.write_bytes(b"user: do the fixture work\nassistant: done\n")
    return path
