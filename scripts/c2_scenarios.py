"""Real public C2 operations on disposable Git consumers, shared with the wheel harness."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import shutil

try:
    from .c1_scenarios import (adr_bundle, adr_caller, adr_markdown, bundle, chore_bundle, criteria, declare_hook, foundation, put_json, tree, snapshot, digest,
                               seed_publication, seed_current, file_hash)
except ImportError:
    from c1_scenarios import (adr_bundle, adr_caller, adr_markdown, bundle, chore_bundle, criteria, declare_hook, foundation, put_json, tree, snapshot, digest,
                              seed_publication, seed_current, file_hash)


# Declared producer of every scripted run; reviews declare another context.
PRODUCER = ("--role", "implementer", "--context", "synthetic implementer session")


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def commit(root, message="fixture checkpoint"):
    git(root, "add", ".")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", message)
    head = git(root, "rev-parse", "HEAD")
    git(root, "update-ref", "refs/remotes/fixture/main", head)
    return head


def setup(workspace, invoke, *, names=("engine", "viewer"), coverage=True, check_code=None, timeout=5, review=None):
    workspace.mkdir(parents=True, exist_ok=True)
    root = workspace / "code with spaces"
    root.mkdir()
    git(root, "init", "-qb", "main")
    config = workspace / "profile.toml"
    lines = ['schema = 3', 'name = "C2 synthetic consumer"', 'trunk_ref = "refs/heads/main"']
    for name in names:
        check = {"id": "unit", "argv": [sys.executable, "src/check.py"], "cwd": ".", "timeout_seconds": timeout}
        if coverage:
            check["acceptance_ids"] = ["AC-001"]
        # TOML inline tables, with JSON strings/arrays for individual values.
        inline = "{" + ", ".join(k + "=" + json.dumps(v) for k, v in check.items()) + "}"
        lines.extend([f'[components.{name}]', 'repo = "."', 'user_facing = false', 'target_ref = "refs/remotes/fixture/main"',
                      'inputs = ["src/**"]', 'generated = ["build/**"]', 'excluded = ["private.env"]',
                      f'verification = [{inline}]'])
    # Existing synthetic scenarios isolate their own gates. FH scenarios leave the
    # profile field absent when exercising the framework default.
    if review is None:
        review = {"enabled": False}
    if review:
        lines.append("[review]")
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in review.items())
    config.write_text("\n".join(lines) + "\n")
    result = invoke(["--json", "init", str(root), "--profile", str(config)])
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    foundation(root, names)
    (root / "src").mkdir()
    (root / "src/check.py").write_text(check_code or 'from pathlib import Path\nassert Path("src/value.txt").read_text() == "saved\\n"\nprint("checked AC-001")\n')
    (root / "src/value.txt").write_text("saved\n")
    (root / ".gitignore").write_text(".roclec/runtime/\nbuild/\nprivate.env\n")
    base = commit(root)
    source = workspace / "bundle"
    record = bundle(source, components=names)
    for args in (("change", "new", "--file", str(source / "change.json")),
                 ("change", "approve", "CHG-001", "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "synthetic test approval",
                  *criteria(root, "approve"))):
        result = invoke(["--project", str(root), "--json", *args])
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
    for name in names:
        result = invoke(["--project", str(root), "--json", "release", "plan", name, "v1.0.0", "--change", "CHG-001"])
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
    return root, base


def branch_scenarios(workspace, invoke, check):
    root, base = setup(workspace / "branch-history", invoke)
    def call(repo, *args, code=0, issue=None):
        result = invoke(["--project", str(repo), "--json", *map(str, args)])
        payload = json.loads(result.stdout)
        check("F2 " + " ".join(map(str, args[:2])), result.returncode == code, result.stdout + result.stderr)
        if issue:
            check("F2 expected " + issue, issue in {item["code"] for item in payload["issues"]}, result.stdout)
        return payload

    def verify(repo, component="engine"):
        return call(repo, "run", "verify", "CHG-001", "--component", component, "--base", base, *PRODUCER)["data"]["run"]

    def observe(repo, run):
        evidence = workspace / "branch-observation.json"
        put_json(evidence, {"model_schema": 2, "kind": "manual", "change_id": "CHG-001", "component": run["component"],
                            "run_id": run["id"], "candidate_digest": run["candidate"]["inputs_digest"],
                            "actor": "Synthetic observer", "context": "Worktree merge fixture", "outcome": "pass",
                            "acceptance_ids": ["AC-001"], "checks": ["Observed test"], "limitations": [], "findings": []})
        return call(repo, "evidence", "record", "--file", evidence)["data"]["evidence"]

    first = verify(root)
    initial_observation = observe(root, first)
    trunk = commit(root)
    left, right = workspace / "left", workspace / "right"
    git(root, "worktree", "add", "-qb", "left", str(left), trunk)
    git(root, "worktree", "add", "-qb", "right", str(right), trunk)
    for worktree, component in ((left, "engine"), (right, "viewer")):
        before = tree(worktree)
        call(worktree, "views", "--write", code=3, issue="OFF_TRUNK")
        check("F2 off-trunk rejection has no writes", tree(worktree) == before, "")
        call(worktree, "change", "start", "CHG-001", "--component", component, "--actor", "Synthetic maintainer")
        after = tree(worktree)
        check("F2 worktree start leaves current and identity registries unchanged",
              all(before[p] == after[p] for p in (".roclec/current.json", ".roclec/identities.json")), "")
    # A same-component start in a second worktree is a fork, unlike independent components.
    fork = call(right, "change", "start", "CHG-001", "--component", "engine", "--actor", "Other synthetic maintainer")
    fork_receipt = fork["data"]["receipt"]
    fork_path = next(iter(fork_receipt["writes"]))
    call(root, "review", "policy", "--change", "CHG-001", "--enabled", "false", "--actor", "Fixture",
         "--reason", "Exercise independent trunk decision chain")
    commit(root)
    records = []
    for worktree in (left, right):
        run = verify(worktree)
        observation = observe(worktree, run)
        check("F2 branch run and observation explicitly replace original scope heads",
              run["supersedes"] == [first["id"]] and observation["supersedes"] == [initial_observation["id"]], "")
        records.append((run, observation))
        commit(worktree)
    for branch in ("left", "right"):
        git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "merge", "--no-ff", "--no-edit", branch)
    call(root, "check", code=1, issue="DECISION_FORK")
    git(root, "rm", fork_path, f".roclec/receipts/{fork_receipt['operation_id']}.json")
    call(root, "change", "start", "CHG-001", "--component", "engine", "--actor", "Other synthetic maintainer")
    check("F2 excluded decision stays in branch history", bool(git(root, "show", f"right:{fork_path}")), "")
    call(root, "check")
    gate = ("check", "--change", "CHG-001", "--component", "engine", "--gate", "verify")
    conflict = call(root, *gate, code=1, issue="AMBIGUOUS_EVIDENCE")
    check("F2 all concurrent run heads are reported", conflict["issues"][0]["actual"] == sorted(r["id"] for r, _ in records), "")
    result = call(root, "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER,
                  code=1, issue="AMBIGUOUS_EVIDENCE")["data"]["run"]
    check("F2 new run supersedes both heads", result["supersedes"] == sorted(r["id"] for r, _ in records), "")
    observation = observe(root, result)
    check("F2 new observation supersedes both heads", observation["supersedes"] == sorted(o["id"] for _, o in records), "")
    call(root, *gate)
    candidate = commit(root)
    plan = workspace / "branch-plan.json"
    git(root, "update-ref", "refs/remotes/fixture/main", trunk)
    call(root, "integrate", "prepare", "CHG-001", "--component", "engine", "--run", result["id"], "--out", plan,
         code=1, issue="TARGET_NOT_INTEGRATED")
    check("F2 rejected prepare creates no output", not plan.exists(), "")
    git(root, "update-ref", "refs/remotes/fixture/main", candidate)
    call(root, "integrate", "prepare", "CHG-001", "--component", "engine", "--run", result["id"], "--out", plan)
    git(root, "update-ref", "refs/remotes/fixture/main", trunk)
    call(root, "operation", "apply", plan, code=3, issue="BASE_CONFLICT")
    git(root, "update-ref", "refs/remotes/fixture/main", candidate)
    call(root, "operation", "apply", plan)
    call(root, "check")


def scenarios(workspace, invoke, check):
    root, base = setup(workspace / "c2", invoke)

    def call(label, *args, expect=0, issue=None, recorded=False):
        before = tree(root)
        result = invoke(["--project", str(root), "--json", *map(str, args)])
        check(label, result.returncode == expect, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        check(label + ": JSON envelope", payload["model_schema"] == 2 and payload["ok"] == (expect == 0), result.stdout)
        if issue:
            check(label + ": issue", issue in [i["code"] for i in payload["issues"]], result.stdout)
        if expect in (1, 2, 3) and not recorded:
            check(label + ": rejection preserves bytes/modes", before == tree(root), result.stdout)
        if recorded:
            check(label + ": execution persisted", payload["data"]["recorded"] and before != tree(root), result.stdout)
        return payload.get("data")

    def expect_status(expected):
        state = call("F1 status reports " + expected, "status")["components"]["engine"]["changes"]
        check("F1 engine change status " + expected, {"id": "CHG-001", "status": expected} in state)

    expect_status("approved")
    call("C2 start", "change", "start", "CHG-001", "--actor", "Fixture maintainer", "--component", "engine")
    expect_status("in-progress")
    # Development is explicitly allowed with uncommitted operational records.
    run = call("I-014 executed check", "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER)["run"]
    run_id = run["id"]
    check("I-014 pass has executed logs and exact inputs", run["status"] == "pass" and run["results"][0]["executed_by_roclec"] and bool(run["candidate"]["inputs_digest"]))
    check("M-28 run records its declared producer", run["producer"] == {"role": "implementer", "context": "synthetic implementer session"}, str(run.get("producer")))
    unattributed = ("run", "verify", "CHG-001", "--component", "engine", "--base", base)
    call("M-28 run without a declared producer is rejected", *unattributed, expect=2, issue="INVALID_INPUT")
    call("M-28 run without a context is rejected", *unattributed, "--role", "implementer", expect=2, issue="INVALID_INPUT")
    call("M-28 run with a non-producer role is rejected", *unattributed, "--role", "reviewer", "--context", "other session", expect=2, issue="INVALID_INPUT")
    call("M-28 run with a multi-line context is rejected", *unattributed, "--role", "implementer", "--context", "first\nsecond", expect=2, issue="INVALID_INPUT")
    expect_status("verified")
    call("I-018 final gate rejects uncommitted metadata", "check", "--change", "CHG-001", "--component", "engine", "--gate", "integrate", expect=1, issue="CANDIDATE_DIRTY")
    (root / "src/new.py").write_text("# new relevant source\n")
    call("I-012 DEF-002 new source invalidates run", "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify", expect=1, issue="EVIDENCE_STALE")
    (root / "src/new.py").unlink()
    (root / "unknown.txt").write_text("unclassified\n")
    call("I-013 unknown paths block before execution", "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER, expect=1, issue="CANDIDATE_INCOMPLETE")
    (root / "unknown.txt").unlink()
    (root / "private.env").write_text("not a source; never read by candidate\n")
    (root / "build").mkdir()
    (root / "build/output").write_text("generated\n")
    call("I-013 explicit ignored exclusions preserve eligibility", "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify")
    (root / ".gitignore").write_text((root / ".gitignore").read_text() + "src/ignored.py\n")
    (root / "src/ignored.py").write_text("# ignored but declared input\n")
    call("I-013 ignored input invalidates run", "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify", expect=1, issue="EVIDENCE_STALE")
    (root / "src/ignored.py").unlink()
    (root / ".gitignore").write_text(".roclec/runtime/\nbuild/\nprivate.env\n")
    policy = call("I-017 enable review", "review", "policy", "--change", "CHG-001", "--enabled", "true", "--actor", "fixture user", "--reason", "test independent review")["policy"]
    call("I-017 absent review blocks verify", "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify", expect=1, issue="REVIEW_REQUIRED")
    run = call("I-017 tests execute while review is missing", "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER,
               expect=1, issue="REVIEW_REQUIRED", recorded=True)["run"]
    check("I-017 completed run differs from verified component", run["status"] == "pass")
    run_id = run["id"]
    evidence_file = workspace / "review.json"

    def report(outcome, kind="independent-review", expect=0, issue=None, **changes):
        record = {"model_schema": 2, "kind": kind, "change_id": "CHG-001", "component": "engine", "run_id": run_id,
                  "candidate_digest": run["candidate"]["inputs_digest"], "actor": "declared fixture reviewer", "context": "synthetic harness report, no model evaluation",
                  "outcome": outcome, "acceptance_ids": ["AC-001"], "checks": ["Observed fixture output"], "limitations": ["No actual independent human review"],
                  "findings": []}
        if kind == "independent-review":
            record.update(policy_id=policy["id"], role="reviewer", resolutions=[])
        record.update(changes)
        record = {k: v for k, v in record.items() if v is not None}
        put_json(evidence_file, record)
        label = "I-016/017 record " + kind + " " + outcome + (" rejected" if expect else "")
        result = call(label, "evidence", "record", "--file", evidence_file, expect=expect, issue=issue)
        return result if expect else result["evidence"]

    report("ready", expect=1, issue="SELF_REVIEW_DECLARED", context="  Synthetic IMPLEMENTER Session ")
    report("ready", expect=2, issue="INVALID_INPUT", role=None)
    report("ready", expect=2, issue="INVALID_INPUT", role="implementer")
    report("pass", "manual", expect=2, issue="INVALID_INPUT", role="reviewer")
    for outcome in ("changes-needed", "incomplete"):
        report(outcome)
        call("I-017 unfavorable review blocks", "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify", expect=1, issue="REVIEW_REQUIRED")
    manual = report("pass", "manual")
    check("I-016 manual report never claims execution", manual["executed_by_roclec"] is False and "argv" not in manual)
    report("ready", findings=[finding("F-001", "minor")])
    call("I-017 current ready permits verify", "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify")
    (root / "src/new.py").write_text("# relevant source\n")
    call("I-017 ready report becomes stale", "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify", expect=1, issue="EVIDENCE_STALE")
    run = call("I-017 new passing run does not refresh a stale report", "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER,
               expect=1, issue="REVIEW_REQUIRED", recorded=True)["run"]
    (root / "src/new.py").unlink()
    run = call("I-019 restore identical inputs and reuse matching review", "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER)["run"]
    run_id = run["id"]
    history = tree(root)
    call("I-017 disable with a recorded reason", "review", "policy", "--change", "CHG-001", "--enabled", "false", "--actor", "fixture user", "--reason", "disable for test")
    check("I-017 reports and findings preserved", all(tree(root).get(p) == v for p, v in history.items() if p.startswith(".roclec/evidence/")))
    viewer = call("I-011 verify second component", "run", "verify", "CHG-001", "--component", "viewer", "--base", base, *PRODUCER)["run"]
    commit(root, "record execution metadata")
    call("I-019 same bytes under descendant commit reuse evidence", "check", "--change", "CHG-001", "--component", "engine", "--gate", "integrate")
    plan_path = workspace / "integration.json"
    prepared = call("I-025 prepare integration without advancing index", "integrate", "prepare", "CHG-001", "--component", "engine", "--run", run_id, "--out", plan_path)["plan"]
    check("I-025 preparation preserves absent contract", not (root / ".roclec/contracts").exists())
    tampered = dict(prepared)
    tampered["writes"] = {"../escape": "0" * 64}
    tampered["operation_id"] = digest({k: v for k, v in tampered.items() if k != "operation_id"})
    bad_plan = workspace / "tampered.json"
    put_json(bad_plan, tampered)
    call("I-027 recomputed malicious plan rejected", "operation", "apply", bad_plan, expect=3, issue="OPERATION_CONFLICT")
    call("I-011 apply first real integration", "operation", "apply", plan_path)
    expect_status("integrated")
    state = call("I-011 inspect partial progress", "inspect", "--change", "CHG-001")
    check("I-011 actual partial vector", state["status"] == "partially-integrated" and state["components"]["engine"] == "integrated" and state["components"]["viewer"] != "integrated")
    integrated_revision = state["integrations"]["engine"]["proposal_digest"]
    snapshot_root = root / ".roclec/changes/CHG-001/revisions" / integrated_revision
    snapshot_record = json.loads((snapshot_root / "change.json").read_text())
    origin = snapshot_record["semantic"]["origins"][0]
    check("FO real integration retains approved source and criterion coverage",
          (snapshot_root / origin["captured"]).is_file()
          and snapshot_record["semantic"]["coverage"]["criteria"][0]["acceptance_ids"] == ["AC-001"])
    current = json.loads((root / ".roclec/current.json").read_text())
    check("I-011 only selected component advances", bool(current["components"]["engine"]) and not current["components"]["viewer"])
    before = tree(root)
    call("I-026 repeated apply returns historical receipt", "operation", "apply", plan_path)
    check("I-026 repeated apply has no writes", before == tree(root))
    # A new explicit approval for pending work retains the first component's
    # original approved intent and integration record.
    folder = root / ".roclec/changes/CHG-001"
    record = json.loads((folder / "change.json").read_text())
    body = (folder / "proposal.md").read_bytes() + b"\nPending participant clarification, explicitly reapproved.\n"
    (folder / "proposal.md").write_bytes(body)
    import hashlib
    record["semantic"]["files"]["proposal.md"] = hashlib.sha256(body).hexdigest()
    record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
    put_json(folder / "change.json", record)
    state = call("C2 pending revision keeps integrated history", "inspect", "--change", "CHG-001")
    check("C2 partial integration survives an unapproved pending revision", state["status"] == "partially-integrated" and not state["approval_current"]
          and state["integrations"]["engine"]["proposal_digest"] != record["proposal_digest"])
    call("C2 explicitly approve pending revision", "change", "approve", "CHG-001", "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "Clarify pending participant",
         *criteria(root, "approve"))
    call("C2 rebind pending release membership only", "release", "plan", "viewer", "v1.0.0", "--change", "CHG-001")
    viewer = call("C2 fresh evidence for pending intent", "run", "verify", "CHG-001", "--component", "viewer", "--base", base, *PRODUCER)["run"]
    commit(root, "record first integration")
    second_plan = workspace / "viewer-integration.json"
    call("I-011 prepare remaining component", "integrate", "prepare", "CHG-001", "--component", "viewer", "--run", viewer["id"], "--out", second_plan)
    call("I-011 integrate remaining component", "operation", "apply", second_plan)
    state = call("I-011 inspect fully integrated change", "inspect", "--change", "CHG-001")
    check("I-011 all participants integrated", state["status"] == "integrated")
    corrections = workspace / "fx-integrated-corrections.json"
    put_json(corrections, [{"id": "R-1", "description": "Clarify the historical change"}])
    call("FX integrated changes need a new change", "reject", "change", "CHG-001",
         "--digest", state["change"]["proposal_digest"], "--actor", "Fixture maintainer",
         "--reason", "Request follow-up", "--consequence", "revise", "--corrections", corrections,
         *criteria(root, "approve", "rejected"), expect=1, issue="INVALID_REFERENCE")
    before = tree(root)
    call("I-026 old receipt never rolls back later index", "operation", "apply", plan_path)
    check("I-026 later index preserved", tree(root) == before)
    call("C2 structural validation after integration", "check")
    call("C3 preparation requires explicit release run and output", "release", "prepare", "engine", "v1.0.0", expect=2, issue="INVALID_INPUT")


def execution_scenarios(workspace, invoke, check):
    cases = [
        ("I-014 missing coverage", dict(coverage=False), "pass", "COVERAGE_MISSING"),
        ("I-015 product failure", dict(check_code='raise AssertionError("fixture product failure")\n'), "fail", "CANDIDATE_INCOMPLETE"),
        ("I-015 timeout", dict(check_code='import time\ntime.sleep(5)\n', timeout=1), "incomplete", "CANDIDATE_INCOMPLETE"),
        ("I-015 changing input", dict(check_code='from pathlib import Path\nPath("src/value.txt").write_text("changed\\n")\n'), "incomplete", "EVIDENCE_STALE"),
        ("I-015 missing executable", {}, "incomplete", "CANDIDATE_INCOMPLETE"),
    ]
    for number, (label, options, status, issue) in enumerate(cases):
        root, base = setup(workspace / f"execution-{number}", invoke, names=("engine",), **options)
        if "missing executable" in label:
            path = root / ".roclec/project.toml"
            path.write_text(path.read_text().replace(json.dumps(sys.executable), '"roclec-fixture-command-does-not-exist"'))
        prefix = ["--project", str(root), "--json"]
        result = invoke([*prefix, "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER])
        payload = json.loads(result.stdout)
        check(label + ": execution rejected verification", result.returncode == 1 and issue in [i["code"] for i in payload["issues"]], result.stdout + result.stderr)
        run = payload["data"]["run"]
        check(label + ": actual run persisted", payload["data"]["recorded"] and run["status"] == status
              and (root / ".roclec/runs" / run["id"] / "manifest.json").is_file(), result.stdout)
        if "missing executable" in label:
            check(label + ": setup differs from product failure", not run["results"][0]["executed_by_roclec"] and "environment" in run["results"][0]["limitation"])
        if "missing coverage" in label:
            evidence_file = workspace / "coverage.json"
            report = {"model_schema": 2, "kind": "manual", "change_id": "CHG-001", "component": "engine", "run_id": run["id"],
                      "candidate_digest": run["candidate"]["inputs_digest"], "actor": "fixture observer", "context": "Synthetic manual observation",
                      "outcome": "pass", "acceptance_ids": ["AC-001"], "checks": ["Observed output meets AC-001"], "limitations": [], "findings": []}
            put_json(evidence_file, report)
            result = invoke([*prefix, "evidence", "record", "--file", str(evidence_file)])
            check("I-014/016 manual coverage imports without executing commands", result.returncode == 0 and not json.loads(result.stdout)["data"]["evidence"]["executed_by_roclec"], result.stdout)
            result = invoke([*prefix, "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify"])
            check("I-014 complete coverage permits verification", result.returncode == 0, result.stdout)
            report["outcome"] = "incomplete"
            put_json(evidence_file, report)
            result = invoke([*prefix, "evidence", "record", "--file", str(evidence_file)])
            check("I-016 retain an incomplete later observation", result.returncode == 0, result.stdout)
            result = invoke([*prefix, "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify"])
            check("I-014 earlier pass cannot hide a newer incomplete observation", result.returncode == 1 and "COVERAGE_MISSING" in [i["code"] for i in json.loads(result.stdout)["issues"]], result.stdout)
            report["outcome"] = "pass"
            report["acceptance_ids"] = ["AC-999"]
            put_json(evidence_file, report)
            before = tree(root)
            result = invoke([*prefix, "evidence", "record", "--file", str(evidence_file)])
            check("I-020 evidence of foreign AC rejected without mutation", result.returncode == 1 and tree(root) == before, result.stdout)


def prepared_fixture(workspace, invoke, *, member_finding=False):
    root, base = setup(workspace, invoke, names=("engine",))
    prefix = ["--project", str(root), "--json"]
    result = invoke([*prefix, "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER])
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    run = json.loads(result.stdout)["data"]["run"]
    if member_finding:
        result = invoke([*prefix, "inspect", "--change", "CHG-001"])
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        policy = json.loads(result.stdout)["data"]["review_policy"]
        file = workspace / "member-review.json"
        put_json(file, {"model_schema": 2, "kind": "independent-review", "change_id": "CHG-001", "component": "engine",
                        "run_id": run["id"], "candidate_digest": run["candidate"]["inputs_digest"], "actor": "fixture reviewer",
                        "context": "Synthetic reviewer session", "role": "reviewer", "policy_id": policy["id"],
                        "outcome": "ready", "acceptance_ids": ["AC-001"], "checks": ["Synthetic observation"],
                        "limitations": [], "findings": [finding("F-1", "major")], "resolutions": []})
        result = invoke([*prefix, "evidence", "record", "--file", str(file)])
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
    commit(root)
    path = workspace / "plan.json"
    result = invoke([*prefix, "integrate", "prepare", "CHG-001", "--component", "engine", "--run", run["id"], "--out", str(path)])
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return root, base, path


def competing_fixture(workspace, invoke):
    root, base, first = prepared_fixture(workspace, invoke)
    prefix = ["--project", str(root), "--json"]

    def must(*args, expect=0):
        result = invoke([*prefix, *map(str, args)])
        if result.returncode != expect:
            raise AssertionError(result.stdout + result.stderr)
        return json.loads(result.stdout)["data"]

    must("operation", "apply", first)
    config = root / ".roclec/project.toml"
    config.write_text(config.read_text().replace(', acceptance_ids=["AC-001"]', ''))
    original = snapshot(("engine",))
    records = []
    for number in (2, 3):
        change_id = f"CHG-{number:03}"
        target = snapshot(("engine",), ac=f"AC-{number:03}", behavior=f"variant {number}")
        source = workspace / change_id
        record = bundle(source, change_id=change_id, base=original, target=target, components=("engine",))
        must("change", "new", "--file", source / "change.json")
        must("change", "approve", change_id, "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "synthetic evolution",
             *criteria(root, "approve"))
        records.append(record)
    must("release", "plan", "engine", "v1.1.0", "--change", "CHG-002", "--change", "CHG-003")
    runs = []
    for record in records:
        run = must("run", "verify", record["id"], "--component", "engine", "--base", base, *PRODUCER, expect=1)["run"]
        if run["status"] != "pass":
            raise AssertionError("Competing fixture checks must pass before attaching manual coverage")
        evidence_file = workspace / (record["id"] + "-observation.json")
        report = {"model_schema": 2, "kind": "manual", "change_id": record["id"], "component": "engine", "run_id": run["id"],
                  "candidate_digest": run["candidate"]["inputs_digest"], "actor": "fixture observer", "context": "Synthetic coverage; no product evaluation",
                  "outcome": "pass", "acceptance_ids": ["AC-002" if record["id"] == "CHG-002" else "AC-003"],
                  "checks": ["Synthetic observation of this proposed AC"], "limitations": ["Structural harness fixture"], "findings": []}
        put_json(evidence_file, report)
        must("evidence", "record", "--file", evidence_file)
        runs.append(run)
    commit(root)
    plans = []
    for record, run in zip(records, runs):
        plan = workspace / (record["id"] + "-plan.json")
        must("integrate", "prepare", record["id"], "--component", "engine", "--run", run["id"], "--out", plan)
        plans.append(plan)
    return root, plans


def conflict_scenarios(workspace, invoke, check, race=None):
    root, plans = competing_fixture(workspace / "competing", invoke)
    commands = [["--project", str(root), "--json", "operation", "apply", str(p)] for p in plans]
    results = race(commands) if race else [invoke(argv) for argv in commands]
    check("I-025/027 exactly one advance on the same base", sorted(r.returncode for r in results) == [0, 3],
          "\n".join(r.stdout + r.stderr for r in results))
    loser = next(r for r in results if r.returncode != 0)
    check("I-025/027 explicit base or operation conflict", any(i["code"] in {"BASE_CONFLICT", "OPERATION_CONFLICT"} for i in json.loads(loser.stdout)["issues"]), loser.stdout)
    records = list((root / ".roclec/integrations/CHG-002").glob("*/*.json")) + list((root / ".roclec/integrations/CHG-003").glob("*/*.json"))
    check("I-025/027 losing change has no integration record", len(records) == 1)
    before = tree(root)
    loser_index = next(i for i, r in enumerate(results) if r.returncode != 0)
    repeated = invoke(commands[loser_index])
    check("I-025 stale plan cannot overwrite the winner", repeated.returncode == 3 and tree(root) == before, repeated.stdout)


def edge_scenarios(workspace, invoke, check):
    root, _ = setup(workspace / "deletion", invoke, names=("engine",))
    prefix = ["--project", str(root), "--json"]
    obsolete = root / "src/obsolete.py"
    obsolete.write_text("# obsolete source\n")
    base = commit(root)
    obsolete.unlink()
    git(root, "add", "-u")
    result = invoke([*prefix, "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER])
    check("I-018 staged development deletion is verifiable", result.returncode == 0, result.stdout)
    manifest = json.loads(result.stdout)["data"]["run"]["candidate"]
    check("I-019 deletion has an explicit manifest marker", manifest["inputs"]["files"]["src/obsolete.py"] == {"type": "deleted"})
    commit(root)
    result = invoke([*prefix, "check", "--change", "CHG-001", "--component", "engine", "--gate", "integrate"])
    check("I-019 committing deletion preserves relevant input fingerprint", result.returncode == 0, result.stdout)
    (root / "src/fresh.py").write_text("# new source\n")
    for staged in (False, True):
        if staged:
            git(root, "add", "src/fresh.py")
        before = tree(root)
        result = invoke([*prefix, "check", "--change", "CHG-001", "--component", "engine", "--gate", "integrate"])
        check("I-018 " + ("staged" if staged else "untracked") + " source rejects final gate", result.returncode == 1 and tree(root) == before
              and "CANDIDATE_DIRTY" in [i["code"] for i in json.loads(result.stdout)["issues"]], result.stdout)
    root, _ = setup(workspace / "separate", invoke, names=("engine",))
    code = root.parent / "external code"
    code.mkdir()
    shutil.copytree(root / "src", code / "src")
    git(code, "init", "-q")
    base = commit(code)
    config = root / ".roclec/project.toml"
    config.write_text(config.read_text().replace('repo = "."', 'repo = "../external code"'))
    prefix = ["--project", str(root), "--json"]
    result = invoke([*prefix, "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER])
    check("I-018 separate configured repo executes checks", result.returncode == 0, result.stdout)
    run_id = json.loads(result.stdout)["data"]["run"]["id"]
    plan = root.parent / "separate-plan.json"
    result = invoke([*prefix, "integrate", "prepare", "CHG-001", "--component", "engine", "--run", run_id, "--out", str(plan)])
    check("I-018 clean code repo eligible with separate spec metadata", result.returncode == 0, result.stdout)
    result = invoke([*prefix, "operation", "apply", str(plan)])
    check("I-011 separate repo integrates without code writes", result.returncode == 0 and not git(code, "status", "--porcelain"), result.stdout)
    root, _, plan = prepared_fixture(workspace / "historical-fix", invoke)
    prefix = ["--project", str(root), "--json"]

    def must(*args):
        result = invoke([*prefix, *map(str, args)])
        check("C2 historical fix: " + " ".join(map(str, args[:2])), result.returncode == 0, result.stdout)
        return json.loads(result.stdout)["data"]

    must("operation", "apply", plan)
    old = snapshot(("engine",))
    # Explicit historical reader fixtures, never a C3 publication claim.
    publication = seed_publication(root, "v1.0.0", old)
    newer = snapshot(("engine",), ac="AC-002", behavior="newer line")
    seed_current(root, newer, names=("engine",))
    source = root.parent / "fix"
    record = bundle(source, change_id="CHG-002", base=old, components=("engine",), kind="fix")
    record["semantic"]["baseline_release"] = {"component": "engine", "version": "v1.0.0"}
    record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
    put_json(source / "change.json", record)
    must("change", "new", "--file", source / "change.json")
    must("change", "approve", "CHG-002", "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "Restore historical contract",
         *criteria(root, "approve"))
    must("release", "plan", "engine", "v1.0.1", "--kind", "hotfix", "--base-tag", "v1.0.0", "--change", "CHG-002")
    run = must("run", "verify", "CHG-002", "--component", "engine", "--base", publication["commit"], *PRODUCER)["run"]
    commit(root)
    fix_plan = root.parent / "fix-plan.json"
    must("integrate", "prepare", "CHG-002", "--component", "engine", "--run", run["id"], "--out", fix_plan)
    must("operation", "apply", fix_plan)
    current = json.loads((root / ".roclec/current.json").read_text())
    integration = json.loads(next((root / ".roclec/integrations/CHG-002/engine").glob("*.json")).read_text())
    check("C2 historical fix preserves newer current pointer", current["components"]["engine"]["CAP-001"] == newer["revision"])
    check("C2 historical fix records the historical contract it actually verifies", integration["contracts"]["CAP-001"] == old["revision"])


def finding(identifier, severity):
    return {"id": identifier, "severity": severity, "location": {"path": "src/check.py", "line": 1},
            "acceptance_ids": ["AC-001"], "condition": "On the synthetic path",
            "impact": "The fixture exposes the recorded behavior", "description": "Synthetic finding"}


def findings_scenarios(workspace, invoke, check):
    workspace = workspace / "findings"
    root, base = setup(workspace, invoke, names=("engine",), review={})
    report_file = workspace / "report.json"
    decision_file = workspace / "decision.json"
    change = "CHG-001"
    scope = {"model_schema": 2, "change_id": change, "component": "engine"}

    def call(repo, *args, failure=False, issue=None, writes=False):
        before = tree(repo) if failure and not writes else None
        result = invoke(["--project", str(repo), "--json", *map(str, args)])
        payload = json.loads(result.stdout)
        label = "FH " + " ".join(map(str, args))
        check(label, (result.returncode in {1, 2}) if failure else result.returncode == 0, result.stdout + result.stderr)
        if issue:
            check(label + " issue", issue in {detail["code"] for detail in payload["issues"]}, result.stdout)
        if before is not None:
            check(label + " rejected without changes", tree(repo) == before, result.stdout)
        return payload

    def record_run(repo, *, blocked=True):
        return call(repo, "run", "verify", change, "--component", "engine", "--base", base, *PRODUCER,
                    failure=blocked, writes=True)["data"]["run"]

    profile_file = root / ".roclec/project.toml"
    profile_text = profile_file.read_text()
    for bad_settings in ('enabled = "false"', 'material_severity = "urgent"', 'unknown = true'):
        profile_file.write_text(profile_text + "\n[review]\n" + bad_settings + "\n")
        call(root, "check", failure=True, issue="INVALID_INPUT")
    profile_file.write_text(profile_text)

    policy = call(root, "inspect", "--change", change)["data"]["review_policy"]
    check("FH a profile without review settings enables review", policy["enabled"])
    initial = record_run(root)

    def review(repo, run, *, findings=(), resolutions=None, context="Synthetic reviewer session",
               actor="fixture reviewer", failure=False, issue=None):
        candidate = run["candidate"]["inputs_digest"]
        resolutions = [{"finding": key, "status": status, "candidate_digest": candidate, "note": "Verified the synthetic candidate"}
                       for key, status in (resolutions or {}).items()]
        report = {**scope, "kind": "independent-review", "run_id": run["id"], "candidate_digest": candidate,
                  "actor": actor, "role": "reviewer", "context": context, "policy_id": policy["id"],
                  "outcome": "ready", "acceptance_ids": ["AC-001"], "checks": ["Observed synthetic behavior"],
                  "limitations": ["Fixture only"], "findings": list(findings), "resolutions": resolutions}
        put_json(report_file, report)
        payload = call(repo, "evidence", "record", "--file", report_file, failure=failure, issue=issue)
        return payload if failure else payload["data"]["evidence"]

    def findings(repo, *flags):
        return call(repo, "list", "findings", "--change", change, *flags)["data"]["findings"]

    def check_gate(repo, gate="verify", **kwargs):
        return call(repo, "check", "--change", change, "--component", "engine", "--gate", gate, **kwargs)

    bad = finding("F-1", "distinctive")
    review(root, initial, findings=[bad], failure=True, issue="INVALID_INPUT")
    del bad["severity"]
    review(root, initial, findings=[bad], failure=True, issue="INVALID_INPUT")

    first = review(root, initial, findings=[finding("F-1", "major"), finding("F-2", "minor")])
    major, minor = (first["id"] + "#" + identifier for identifier in ("F-1", "F-2"))
    human = invoke(["--project", str(root), "list", "findings", "--change", change, "--open"])
    check("FH the human-readable list shows identity, location and state record",
          human.returncode == 0 and all(part in human.stdout for part in (major, "src/check.py:1", "State record")), human.stdout)
    blocked = check_gate(root, failure=True, issue="FINDINGS_OPEN")
    check("FH default threshold blocks the major and lists its key", major in blocked["issues"][0]["actual"], str(blocked))
    (root / "src/second.py").write_text("# synthetic new candidate\n")
    replacement = record_run(root)
    missing = review(root, replacement, resolutions={minor: "still-open"}, failure=True, issue="FINDING_RESOLUTION_REQUIRED")
    check("FH omission lists the finding from the previous candidate", major in missing["issues"][0]["actual"], str(missing))
    review(root, replacement, resolutions={major: "fixed", minor: "still-open", first["id"] + "#F-99": "fixed"},
           failure=True, issue="INVALID_REFERENCE")
    review(root, replacement, resolutions={major: "fixed", minor: "still-open"},
           context="  SYNTHETIC IMPLEMENTER SESSION  ", failure=True, issue="SELF_REVIEW_DECLARED")
    ready = review(root, replacement, resolutions={major: "still-open", minor: "still-open"})
    trunk = commit(root)
    check("FH predecessor finding survives a favorable review of a new candidate",
          {row["key"]: row["status"] for row in findings(root, "--open")} == {major: "still-open", minor: "still-open"})
    check("FH inspect and list show the state-producing review",
          call(root, "inspect", "--change", change)["data"]["findings"] == findings(root)
          and all(row["state_record"] == ready["id"] for row in findings(root)))
    check_gate(root, "integrate", failure=True, issue="FINDINGS_OPEN")

    branches = {}
    for name, status in (("fixed", "fixed"), ("open", "still-open"), ("second-fix", "fixed")):
        branch = "fh-" + name
        worktree = workspace / branch
        git(root, "worktree", "add", "-qb", branch, str(worktree), trunk)
        actor = "second fixture reviewer" if name == "second-fix" else "fixture reviewer"
        review(worktree, replacement, resolutions={major: status, minor: "still-open"}, actor=actor)
        commit(worktree)
        branches[name] = branch
    dispositions = {}
    for status in ("accepted", "invalid"):
        branch = workspace / f"fh-user-{status}"
        git(root, "worktree", "add", "-qb", branch.name, str(branch), trunk)
        put_json(decision_file, {**scope, "kind": "finding-decision", "status": status, "findings": [major],
                                 "actor": "fixture user", "reason": "Disposition of the synthetic finding"})
        dispositions[status] = call(branch, "evidence", "record", "--file", decision_file)["data"]["evidence"]
        commit(branch)
        branches[status] = branch.name

    def merge_reviews(label, *order):
        worktree = workspace / label
        git(root, "worktree", "add", "-qb", "fh-" + label, str(worktree), trunk)
        for name in order:
            git(worktree, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "merge", "--no-ff", "--no-edit", branches[name])
        return worktree

    agreed = merge_reviews("agreed", "fixed", "second-fix")
    resolved = next(row for row in findings(agreed) if row["key"] == major)
    check("FH concurrent matching fixes remain fixed", resolved["status"] == "fixed"
          and not resolved["ambiguous"] and len(resolved["state_records"]) == 2, str(resolved))
    check_gate(agreed)

    human_priority = merge_reviews("human-priority", "accepted", "open")
    resolved = next(row for row in findings(human_priority) if row["key"] == major)
    check("FH a human disposition survives a concurrent reviewer observation",
          resolved["status"] == "accepted" and resolved["state_record"] == dispositions["accepted"]["id"], str(resolved))
    review(human_priority, replacement, resolutions={major: "still-open", minor: "still-open"},
           failure=True, issue="INVALID_REFERENCE")
    check_gate(human_priority)

    contested = merge_reviews("human-conflict", "accepted", "invalid")
    resolved = next(row for row in findings(contested) if row["key"] == major)
    check("FH conflicting human decisions require a human reconciliation",
          resolved["status"] == "still-open" and resolved["ambiguous"] and resolved["requires_human"], str(resolved))
    review(contested, replacement, resolutions={major: "fixed", minor: "still-open"},
           failure=True, issue="FINDING_DECISION_REQUIRED")
    call(contested, "evidence", "record", "--file", decision_file)
    check_gate(contested)

    outcomes = []
    for index, order in enumerate((("fixed", "open"), ("open", "fixed"))):
        worktree = merge_reviews(f"merge-{index}", *order)
        outcomes.append(findings(worktree))
        check_gate(worktree, failure=True, issue="FINDINGS_OPEN")
    check("FH both merge orders retain the same open conflict", outcomes[0] == outcomes[1]
          and {row["key"]: row["status"] for row in outcomes[0]}[major] == "still-open", str(outcomes))

    merged = workspace / "merge-0"
    review(merged, replacement, resolutions={major: "still-open", minor: "still-open"},
           failure=True, issue="INVALID_REFERENCE")
    result = review(merged, replacement, resolutions={major: "fixed", minor: "still-open"},
                    findings=[finding("F-3", "info"), finding("F-4", "minor"), finding("F-5", "info")])
    passed = check_gate(merged)["data"]
    check("FH minor findings remain visible while verify passes", minor in json.dumps(passed), str(passed))

    fut_file = workspace / "future.json"
    put_json(fut_file, {"model_schema": 2, "id": "FUT-001", "source": {"location": "docs/reference.md", "locator": "Fixture"},
                        "finding": "Follow-up", "impact": "Fixture only", "questions": []})
    call(root, "fut", "capture", "--file", fut_file)
    fut_commit = commit(root)
    git(merged, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "merge", "--no-edit", fut_commit)

    def decide(identifier, status, *, failure=False, **extra):
        key = result["id"] + "#" + identifier
        put_json(decision_file, {**scope, "kind": "finding-decision", "status": status, "findings": [key],
                                 "actor": "fixture user", "reason": "Recorded user disposition", **extra})
        payload = call(merged, "evidence", "record", "--file", decision_file, failure=failure)
        return key, payload

    decide("F-3", "accepted", actor="", failure=True)
    decide("F-5", "deferred", failure=True)
    decide("F-5", "deferred", fut_id="FUT-999", failure=True)
    for identifier, status, extra in (("F-3", "accepted", {}), ("F-4", "invalid", {}), ("F-5", "deferred", {"fut_id": "FUT-001"})):
        key, decision = decide(identifier, status, **extra)
        row = next(row for row in findings(merged) if row["key"] == key)
        check("FH human disposition is derived in a worktree", row["status"] == status
              and row["state_record"] == decision["data"]["evidence"]["id"], str(row))
    call(merged, "check")
    check("FH --open filters out all closed states", [row["key"] for row in findings(merged, "--open")] == [minor])
    review(merged, replacement, resolutions={major: "still-open", minor: "still-open"},
           failure=True, issue="INVALID_REFERENCE")
    repeated = review(merged, replacement, resolutions={minor: "still-open"},
                      findings=[{**finding("F-1", "info"), "recurs_from": major}])
    rows = {row["key"]: row for row in findings(merged)}
    check("FH recurrence keeps the original finding fixed",
          rows[major]["status"] == "fixed" and rows[repeated["id"] + "#F-1"]["recurs_from"] == major)
    config = merged / ".roclec/project.toml"
    config.write_text(config.read_text() + '\n[review]\nmaterial_severity = "minor"\n')
    record_run(merged)
    blocked = check_gate(merged, failure=True, issue="FINDINGS_OPEN")
    check("FH the configured material threshold blocks the previously nonmaterial finding",
          blocked["issues"][0]["actual"] == [minor], str(blocked))
    call(root, "review", "policy", "--change", change, "--enabled", "false", "--actor", "",
         "--reason", "Fixture waiver", failure=True)
    call(root, "review", "policy", "--change", change, "--enabled", "false", "--actor", "fixture user",
         "--reason", "Fixture waiver")
    check_gate(root)
    corrupted = root / f".roclec/evidence/{first['id']}.json"
    original = corrupted.read_bytes()
    corrupted.write_text("{}")
    call(root, "status")
    call(root, "list", "changes")
    inspected = call(root, "inspect", "--change", change)["data"]
    check("FH inspect preserves the change and reports evidence corruption",
          inspected["change"]["id"] == change and "UNSUPPORTED_SCHEMA" in {issue["code"] for issue in inspected["issues"]})
    call(root, "list", "findings", "--change", change, failure=True, issue="UNSUPPORTED_SCHEMA")
    corrupted.write_bytes(original)


def adr_scenarios(workspace, invoke, check):
    """ADR gates, pins and candidate classification with real runs and Git integration."""
    root, base = setup(workspace / "c2-adr", invoke, names=("engine",))
    call = adr_caller(root, invoke, check)
    adr_path = root / "docs/adr/ADR-001.md"
    adr_path.parent.mkdir(parents=True)
    adr_path.write_text(adr_markdown("ADR-001: Decision"), encoding="utf-8")
    call("C2 ADR registers", "reference", "add", "ADR-001", "--path", "docs/adr/ADR-001.md", "--component", "engine", "--role", "decision")
    members = ["CHG-001"]

    def ready(change_id, declaration, *, base_snapshot=None):
        folder = adr_bundle(workspace / "adr-bundles" / change_id, change_id, declaration, base=base_snapshot)
        call(f"C2 ADR seal {change_id}", "change", "seal", folder)
        call(f"C2 ADR new {change_id}", "change", "new", "--file", folder / "change.json")
        record = json.loads((folder / "change.json").read_text())
        call(f"C2 ADR approve {change_id}", "change", "approve", change_id, "--digest", record["proposal_digest"],
             "--actor", "fixture", "--reason", "Approved scope", *criteria(root, "approve"))
        members.append(change_id)
        call(f"C2 ADR assign {change_id}", "release", "plan", "engine", "v1.0.0", *[a for m in members for a in ("--change", m)])
        return record

    def gate(label, change_id="CHG-002", **kwargs):
        return call(label, "check", "--change", change_id, "--component", "engine", "--gate", "implement", **kwargs)

    def agree(label):
        call(label, "foundation", "agree", "--ref", "ADR-001", "--actor", "Maintainer", "--reason", "Accepted ADR",
             *criteria(root, "foundation"))

    def integrate(change_id, run=None):
        run = run or call(f"C2 ADR verify {change_id}", "run", "verify", change_id, "--component", "engine", "--base", base, *PRODUCER)["data"]["run"]
        commit(root)
        plan = workspace / f"adr-{change_id}-plan.json"
        call(f"C2 ADR prepare {change_id}", "integrate", "prepare", change_id, "--component", "engine", "--run", run["id"], "--out", plan)
        call(f"C2 ADR apply {change_id}", "operation", "apply", plan)

    # A registered ADR is a candidate input without profile classification.
    original = adr_path.read_bytes()
    notes = root / "docs/adr/notes.md"
    notes.write_text("# Unregistered notes\n")
    incomplete = call("C2 ADR folder files still need registration or classification", "run", "verify", "CHG-001", "--component", "engine",
                      "--base", base, *PRODUCER, expect=1, issue="CANDIDATE_INCOMPLETE")
    check("C2 ADR only the unregistered file is unclassified", incomplete["issues"][0]["actual"] == ["docs/adr/notes.md"], str(incomplete))
    notes.unlink()
    run = call("C2 ADR registered file is classified as an input", "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER)["data"]["run"]
    candidate = run["candidate"]
    check("C2 ADR candidate input", run["status"] == "pass" and candidate["categories"]["docs/adr/ADR-001.md"] == "input"
          and candidate["inputs"]["files"]["docs/adr/ADR-001.md"]["sha256"] == file_hash(original), str(candidate["categories"]))
    check("C2 ADR is a file input, not a foundation reference", "ADR-001" not in [r["id"] for r in candidate["inputs"]["references"]], "")
    adr_path.write_text(adr_markdown("ADR-001: Edited after the run"), encoding="utf-8")
    call("C2 ADR edit invalidates earlier evidence", "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify",
         expect=1, issue="EVIDENCE_STALE")
    adr_path.write_bytes(original)
    integrate("CHG-001", run)

    # A cited ADR must be accepted with the pinned bytes before work starts.
    ready("CHG-002", {"adrs": [{"id": "ADR-001"}]}, base_snapshot=snapshot(("engine",)))
    blocked = gate("C2 ADR proposed blocks the implement gate", expect=1, issue="ADR_NOT_ACCEPTED")
    check("C2 ADR gate names the proposed ADR", [(f["id"], f["state"]) for f in blocked["issues"][0]["actual"]] == [("ADR-001", "proposed")], str(blocked))
    call("C2 ADR proposed blocks change start", "change", "start", "CHG-002", "--component", "engine", "--actor", "Maintainer",
         expect=1, issue="ADR_NOT_ACCEPTED")
    agree("C2 ADR agreement")
    gate("C2 ADR accepted passes the implement gate")
    call("C2 ADR accepted permits change start", "change", "start", "CHG-002", "--component", "engine", "--actor", "Maintainer")
    adr_path.write_text(adr_markdown("ADR-001: Revised decision"), encoding="utf-8")
    agree("C2 ADR re-agreement of different content")
    stale = gate("C2 ADR pin goes stale after re-agreeing different content", expect=1, issue="ADR_PIN_STALE")
    check("C2 ADR stale pin differs from the agreed bytes", stale["issues"][0]["actual"][0]["agreed"] == file_hash(adr_path.read_bytes())
          and stale["issues"][0]["actual"][0]["pinned"] != stale["issues"][0]["actual"][0]["agreed"], str(stale))

    # Integrated changes keep their pin after a later supersession.
    cited = ready("CHG-003", {"adrs": [{"id": "ADR-001"}]}, base_snapshot=snapshot(("engine",)))
    commit(root)
    gate("C2 ADR accepted ADR with a current pin passes", "CHG-003")
    integrate("CHG-003")
    check("C2 ADR citing change integrated", call("C2 ADR inspect integrated change", "inspect", "--change", "CHG-003")["data"]["status"] == "integrated", "")
    (root / "docs/adr/ADR-002.md").write_text(adr_markdown("ADR-002: Replacement"), encoding="utf-8")
    call("C2 ADR registers the replacement", "reference", "add", "ADR-002", "--path", "docs/adr/ADR-002.md", "--component", "engine",
         "--role", "decision", "--supersedes", "ADR-001")
    call("C2 ADR agrees the replacement", "foundation", "agree", "--ref", "ADR-002", "--actor", "Maintainer", "--reason", "Accepted ADR",
         *criteria(root, "foundation"))
    adr_path.write_text(adr_markdown("ADR-001: Edited after integration"), encoding="utf-8")
    check("C2 ADR is superseded", call("C2 ADR inspect superseded", "inspect", "--adr", "ADR-001")["data"]["state"] == "superseded", "")
    call("C2 ADR check stays green after supersession and edit", "check")
    gate("C2 ADR integrated change keeps passing its gate", "CHG-003")
    changes = call("C2 ADR changes citing ADR-001", "inspect", "--adr", "ADR-001")["data"]["changes"]
    pinned = cited["semantic"]["architecture_decisions"]["adrs"][0]["sha256"]
    check("C2 ADR integrated change keeps its pin", [(c["id"], c["status"], c["pin_current"], c["sha256"]) for c in changes
                                                      if c["id"] == "CHG-003"] == [("CHG-003", "integrated", False, pinned)], str(changes))


CHORE_CRITERIA = [{"id": "CR-005", "status": "met"}]


def chore_scenarios(workspace, invoke, check):
    """A chore (no observable behavior): plan, approve, implement, verify, integrate; no spec, release or review."""
    # The profile enables review and its only check cites AC-001: neither may bind a chore.
    root, base = setup(workspace / "c2-chore", invoke, names=("engine",), review={"enabled": True})
    call = adr_caller(root, invoke, check)
    approval = workspace / "chore-criteria.json"
    put_json(approval, CHORE_CRITERIA)
    bundles = workspace / "chore-bundles"

    drafts = []

    def new(label, change_id, *, expect=0, issue=None, **kwargs):
        folder = bundles / f"{change_id}-{len(drafts)}"
        drafts.append(folder)
        record = chore_bundle(folder, change_id=change_id, **kwargs)
        call(label, "change", "new", "--file", folder / "change.json", expect=expect, issue=issue)
        return record

    def covered(semantic):
        row = semantic["coverage"]["criteria"][0]
        row.pop("reason")
        row.update(status="covered", acceptance_ids=["AC-001"])

    def approve(label, record, *extra, expect=0, issue=None):
        return call(label, "change", "approve", record["id"], "--digest", record["proposal_digest"], "--actor", "Fixture owner",
                    "--reason", "Approved chore plan", *extra, expect=expect, issue=issue)

    # Abuse guards: a chore cannot touch a contract, an obligation, a prototype or a behavior-bearing origin.
    abuse = {
        "bases": lambda s: s.update(bases=[{"capability_id": "CAP-001", "component": "engine", "revision": None}]),
        "deltas": lambda s: s.update(deltas=[{"op": "add", "capability_id": "CAP-001", "requirement_id": "REQ-001"}]),
        "prototypes": lambda s: s.update(prototypes=[{"path": "docs/screen.html", "sha256": "0" * 64}]),
        "fixes": lambda s: s.update(fixes=[]),
    }
    for key, mutate in abuse.items():
        new(f"C2 chore cannot declare {key}", "CHG-101", mutate=mutate, expect=1, issue="INVALID_REFERENCE")
    new("C2 chore cannot originate in a story", "CHG-101", origin_kind="story", expect=1, issue="INVALID_ORIGIN")
    new("C2 chore cannot cover an origin criterion with ACs", "CHG-101", expect=1, issue="INVALID_COVERAGE",
        mutate=covered)

    # A flow without [kinds.chore] refuses chores; existing kinds are unaffected.
    flow_path = root / ".roclec/flow.toml"
    agreed = flow_path.read_bytes()
    table = b'[kinds.chore]\nstages = ["approve", "plan", "implement", "verify", "integrate"]\ncriteria = ["CR-005"]\n'
    check("C2 chore seeded flow enables chores", table in agreed, agreed.decode())
    flow_path.write_bytes(agreed.replace(table, b""))
    new("C2 chore needs [kinds.chore] in the flow", "CHG-101", expect=2, issue="CHANGE_KIND_DISABLED")
    flow_path.write_bytes(agreed)

    record = new("C2 chore imports", "CHG-101")
    view = call("C2 chore inspects", "inspect", "--change", "CHG-101")["data"]
    check("C2 chore is a draft with no ACs", view["status"] == "draft", str(view["status"]))
    approve("C2 chore approval evaluates the chore criteria, not the approve checkpoint's", record,
            *criteria(root, "approve"), expect=2, issue="CRITERIA_MISMATCH")
    decision = approve("C2 chore approval", record, "--criteria", approval)["data"]["decision"]
    check("C2 chore approval records the chore evaluation", decision["criteria"] == CHORE_CRITERIA, str(decision))
    refused = call("C2 chore never joins a release", "release", "plan", "engine", "v1.0.0", "--change", "CHG-001",
                   "--change", "CHG-101", expect=1, issue="VERSION_INVALID")
    check("C2 chore release refusal names the chore", refused["issues"][0]["entity"] == "CHG-101", str(refused["issues"]))
    gate = call("C2 chore implement gate needs no release assignment", "check", "--change", "CHG-101", "--component", "engine",
                "--gate", "implement")
    check("C2 chore gate names no release", gate["data"]["release"] is None, str(gate["data"]))
    call("C2 chore starts", "change", "start", "CHG-101", "--component", "engine", "--actor", "Fixture implementer")

    (root / "src/tooling.json").write_text('{"lint": true}\n')
    commit(root, "chore: add workspace tooling")
    run = call("C2 chore runs every configured check (its AC tag covers nothing)", "run", "verify", "CHG-101",
               "--component", "engine", "--base", base, *PRODUCER)["data"]["run"]
    check("C2 chore run passed", run["status"] == "pass", str(run["status"]))
    call("C2 chore verify gate needs no review by default", "check", "--change", "CHG-101", "--component", "engine", "--gate", "verify")
    stages = {s["stage"]: s for s in call("C2 chore inspect stages", "inspect", "--change", "CHG-101")["data"]["flow"]["stages"]}
    states = {name: (stage.get("change") or stage["components"]["engine"])["status"] for name, stage in stages.items()}
    check("C2 chore lane in conformance", {k: states[k] for k in ("define", "design", "plan", "review", "release")}
          == {"define": "n/a", "design": "n/a", "plan": "done", "review": "n/a", "release": "n/a"}, str(states))
    check("C2 chore approve presents the chore criteria", stages["approve"]["checkpoint"]["criteria"] == ["CR-005"],
          str(stages["approve"]["checkpoint"]))
    commit(root, "record chore run")
    plan = workspace / "chore-plan.json"
    call("C2 chore prepares integration", "integrate", "prepare", "CHG-101", "--component", "engine", "--run", run["id"], "--out", plan)
    call("C2 chore integrates", "operation", "apply", plan)
    final = call("C2 chore inspect after integration", "inspect", "--change", "CHG-101")["data"]
    check("C2 chore integrated", final["status"] == "integrated", str(final["status"]))
    check("C2 chore left contracts untouched", json.loads((root / ".roclec/current.json").read_text())["components"]["engine"] == {},
          (root / ".roclec/current.json").read_text())

    # Existing kinds keep the guard a chore skips: a refactor without AC-001 cannot run the AC-tagged check.
    folder = workspace / "refactor-bundle"
    refactor = bundle(folder, change_id="CHG-103", components=("engine",), kind="refactor")
    call("C2 refactor imports", "change", "new", "--file", folder / "change.json")
    call("C2 refactor approval", "change", "approve", "CHG-103", "--digest", refactor["proposal_digest"], *FLOW_ACTOR,
         *criteria(root, "approve"))
    call("C2 refactor joins the release", "release", "plan", "engine", "v1.0.0", "--change", "CHG-001", "--change", "CHG-103")
    call("C2 refactor still refuses a check citing an inapplicable AC", "run", "verify", "CHG-103", "--component", "engine",
         "--base", base, *PRODUCER, expect=1, issue="INVALID_REFERENCE")

    # A chore may originate in a FUT and defer an origin criterion to another FUT; it never covers one.
    for number in (1, 2):
        fut = {"model_schema": 2, "id": f"FUT-{number:03}", "source": {"location": "docs/reference.md", "locator": "Synthetic context"},
               "finding": "Workspace tooling is missing", "impact": "Blocks the first story", "questions": ["Which linter?"]}
        put_json(workspace / f"chore-fut-{number}.json", fut)
        call(f"C2 chore FUT {number} captured", "fut", "capture", "--file", workspace / f"chore-fut-{number}.json")

    def deferred(semantic):
        row = semantic["coverage"]["criteria"][0]
        row.pop("reason")
        row.update(status="deferred", fut="FUT-002")

    from_fut = new("C2 chore from a FUT imports", "CHG-104", origin_kind="fut", origin_id="FUT-001", mutate=deferred)
    approve("C2 chore from an unpromoted FUT cannot be approved", from_fut, "--criteria", approval, expect=1, issue="INVALID_ORIGIN")
    call("C2 FUT promoted to the chore", "fut", "decide", "FUT-001", "--outcome", "promoted", "--target", "CHG-104", *FLOW_ACTOR)
    approve("C2 chore from a promoted FUT approved", from_fut, "--criteria", approval)

    # A lane that lists review demands the independent review again.
    flow_path.write_bytes(agreed.replace(b'stages = ["approve", "plan", "implement", "verify", "integrate"]',
                                         b'stages = ["approve", "plan", "implement", "verify", "review", "integrate"]'))
    call("C2 chore lane with review is agreed", "foundation", "agree", "--ref", "flow", *FLOW_ACTOR, *criteria(root, "foundation"))
    second = new("C2 second chore imports", "CHG-102")
    approve("C2 second chore approval", second, "--criteria", approval)
    call("C2 second chore starts", "change", "start", "CHG-102", "--component", "engine", "--actor", "Fixture implementer")
    (root / "src/tooling.json").write_text('{"lint": true, "format": true}\n')
    commit(root, "chore: add formatter")
    ran = invoke(["--project", str(root), "--json", "run", "verify", "CHG-102", "--component", "engine", "--base", base, *PRODUCER])
    check("C2 reviewed chore run is recorded but not verified", ran.returncode == 1
          and "REVIEW_REQUIRED" in [i["code"] for i in json.loads(ran.stdout)["issues"]], ran.stdout + ran.stderr)
    call("C2 reviewed chore needs its review", "check", "--change", "CHG-102", "--component", "engine", "--gate", "verify",
         expect=1, issue="REVIEW_REQUIRED")

    # A required plan session is the chore's authoring evidence at approval; it may precede the import.
    flow_text = flow_path.read_text()
    head, plan_block = flow_text.split("[stages.plan]\n", 1)
    plan_block, tail = plan_block.split("\n\n", 1)
    check("C2 chore plan stage is relaxed by the fixture", 'session_evidence = "optional"' in plan_block, plan_block)
    flow_path.write_text(head + "[stages.plan]\n" + plan_block.replace('session_evidence = "optional"', 'session_evidence = "required"')
                         + "\n\n" + tail)
    call("C2 chore flow requiring plan sessions is agreed", "foundation", "agree", "--ref", "flow", *FLOW_ACTOR, *criteria(root, "foundation"))
    record_session = session_importer(call, workspace / "chore-sessions", "chore")
    unplanned = new("C2 chore without a plan session imports", "CHG-105")
    record_session("C2 define session for the unplanned chore", "define", "specifier", change_id="CHG-105")
    approve("C2 chore approval needs the plan session, not a define session", unplanned, "--criteria", approval,
            expect=1, issue="SESSION_REQUIRED")
    planned = record_session("C2 plan session precedes the chore import", "plan", "implementer", change_id="CHG-106")
    record = new("C2 chore citing its plan session imports", "CHG-106", mutate=lambda s: s.update(sessions=[planned]))
    approve("C2 chore with its plan session approved", record, "--criteria", approval)

    # Dropping [kinds.chore] refuses pending chores but never reopens integrated ones.
    text = flow_path.read_text()
    start = text.index("\n[kinds.chore]\n") + 1  # The table, not the header comment that mentions it.
    end = text.index("\n\n", start) + 2
    # Plan sessions go back to optional: the approve gate re-reads session demands from the current flow for
    # every kind, which this step does not exercise.
    flow_path.write_text((text[:start] + text[end:]).replace('session_evidence = "required"', 'session_evidence = "optional"'))
    call("C2 flow without chores is agreed", "foundation", "agree", "--ref", "flow", *FLOW_ACTOR, *criteria(root, "foundation"))
    call("C2 integrated chore keeps passing its approve gate", "check", "--change", "CHG-101", "--component", "engine",
         "--gate", "approve")
    call("C2 integrated chore keeps passing its implement gate", "check", "--change", "CHG-101", "--component", "engine",
         "--gate", "implement")
    call("C2 pending chore is refused once the flow drops chores", "check", "--change", "CHG-106", "--component", "engine",
         "--gate", "implement", expect=2, issue="CHANGE_KIND_DISABLED")
    stages = {s["stage"]: s for s in call("C2 integrated chore inspects", "inspect", "--change", "CHG-101")["data"]["flow"]["stages"]}
    check("C2 integrated chore define entry lists no sessions", stages["define"]["change"] == {
        "status": "n/a", "record": None, "actor": None, "criteria": [], "kind": "chore", "sessions": []}, str(stages["define"]))


MERGE = ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "merge", "--no-ff", "--no-edit")
FLOW_ACTOR = ("--actor", "Fixture owner", "--reason", "Synthetic human decision")


def skill_scenarios(workspace, invoke, check):
    """A knowledge skill is a file input of the components it names; its host copy is operational."""
    root, base = setup(workspace / "c2-skill", invoke, names=("engine",))
    call = adr_caller(root, invoke, check)
    name = "conventions"
    folder = root / ".agents/skills" / name
    for relative, body in {"SKILL.md": "# Conventions\n", "examples/handler.md": "# Handler example\n", ".hidden": "hidden rule\n"}.items():
        (folder / relative).parent.mkdir(parents=True, exist_ok=True)
        (folder / relative).write_text(body, encoding="utf-8")
    verify = ("run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER)
    incomplete = call("C2 SK unregistered skill files need registration or classification", *verify, expect=1, issue="CANDIDATE_INCOMPLETE")
    check("C2 SK every unregistered skill file is unclassified", incomplete["issues"][0]["actual"] == sorted(
        f".agents/skills/{name}/{inner}" for inner in (".hidden", "SKILL.md", "examples/handler.md")), str(incomplete["issues"][0]["actual"]))
    call("C2 SK skill registers", "reference", "add", name, "--path", f".agents/skills/{name}", "--role", "skill", "--component", "engine")
    call("C2 SK skill agreement", "foundation", "agree", "--ref", name, "--actor", "Maintainer", "--reason", "Agreed",
         *criteria(root, "foundation"))
    # The host copy `roclec skills` writes; the full installer would add unclassified stage files this fixture profile does not declare.
    shutil.copytree(folder, root / ".claude/skills" / name)
    run = call("C2 SK registered skill is classified", *verify)["data"]["run"]
    categories, inputs = run["candidate"]["categories"], run["candidate"]["inputs"]["files"]
    check("C2 SK canonical files are inputs, copies operational", run["status"] == "pass" and all(
        categories[f".agents/skills/{name}/{inner}"] == "input" and categories[f".claude/skills/{name}/{inner}"] == "operational"
        and f".agents/skills/{name}/{inner}" in inputs and f".claude/skills/{name}/{inner}" not in inputs
        for inner in (".hidden", "SKILL.md", "examples/handler.md")), str(categories))
    (folder / "examples/handler.md").write_text("# Handler example, revised\n", encoding="utf-8")
    call("C2 SK skill re-agreement", "foundation", "agree", "--ref", name, "--actor", "Maintainer", "--reason", "Re-agreed",
         *criteria(root, "foundation"))
    call("C2 SK editing the skill invalidates earlier evidence", "check", "--change", "CHG-001", "--component", "engine", "--gate", "verify",
         expect=1, issue="EVIDENCE_STALE")


def flow_scenarios(workspace, invoke, check):
    """FF hooks and flow edits across real Git branches merged in both orders.

    Hook checkpoints are chained per (change, component); decisions on different chains never
    fork, whichever side holds them. A flow edited on a branch is just a changed process file:
    merging it never counts as agreement.
    """
    workspace = workspace / "flow"

    def prepared(name):
        root, base = setup(workspace / name, invoke)
        call = adr_caller(root, invoke, check)
        declare_hook(root, "pre-implement")
        declare_hook(root, "pre-integrate", declared={"CR-007": "The tested candidate is the one to integrate."})
        call(f"FF {name} agrees the edited flow", "foundation", "agree", "--ref", "flow", *FLOW_ACTOR, *criteria(root, "foundation"))
        call(f"FF {name} regenerates the flow view", "views", "--write")
        commit(root)
        digest_ = json.loads((root / ".roclec/changes/CHG-001/change.json").read_text())["proposal_digest"]
        runs = {}
        for component in ("engine", "viewer"):
            call(f"FF {name} pre-implement {component}", "checkpoint", "CHG-001", "--hook", "pre-implement",
                 "--component", component, "--digest", digest_, "--outcome", "approved", *FLOW_ACTOR)
            runs[component] = call(f"FF {name} run {component}", "run", "verify", "CHG-001", "--component", component,
                                   "--base", base, *PRODUCER)["data"]["run"]
        commit(root)
        return root, base, call, runs

    def integrate_hook(call, repo, label, runs, component):
        run = runs[component]
        return call(label, "checkpoint", "CHG-001", "--hook", "pre-integrate", "--component", component,
                    "--digest", run["candidate"]["inputs_digest"], "--run", run["id"], "--outcome", "approved",
                    *FLOW_ACTOR, *criteria(repo, "pre-integrate"), project=repo)

    def gate(call, repo, label, component, name, **kwargs):
        return call(label, "check", "--change", "CHG-001", "--component", component, "--gate", name, project=repo, **kwargs)

    def hooks(call, repo, label):
        """Derived hook state per stage and component; record ids and candidate digests differ per repository."""
        stages = {row["stage"]: row for row in call(label, "inspect", "--change", "CHG-001", project=repo)["data"]["flow"]["stages"]}
        return {(stage, component): (row["hook"]["name"], row["hook"]["status"])
                for stage in ("implement", "integrate") for component, row in stages[stage]["components"].items()}

    # 1. Checkpoints are trunk-only; starts and runs happen on branches. Trunk records the hooks of two
    # components while two branches start them, and the merge order must not matter.
    states = {}
    for order in (("left", "right"), ("right", "left")):
        tag = "-".join(order)
        root, base, call, runs = prepared("c2-flow-" + tag)
        trunk = git(root, "rev-parse", "HEAD")
        trees = {}
        for branch in ("left", "right"):
            trees[branch] = workspace / f"{branch}-{tag}"
            git(root, "worktree", "add", "-qb", branch, str(trees[branch]), trunk)
        call(f"FF {tag} a branch cannot record a checkpoint", "checkpoint", "CHG-001", "--hook", "pre-integrate",
             "--component", "engine", "--digest", runs["engine"]["candidate"]["inputs_digest"], "--run", runs["engine"]["id"],
             "--outcome", "approved", *FLOW_ACTOR, *criteria(root, "pre-integrate"), project=trees["left"], expect=3, issue="OFF_TRUNK")
        for branch, component in (("left", "engine"), ("right", "viewer")):
            call(f"FF {tag} {branch} starts {component}", "change", "start", "CHG-001", "--component", component,
                 "--actor", "Synthetic maintainer", project=trees[branch])
            commit(trees[branch], f"start {component}")
        gate(call, root, f"FF {tag} trunk blocks the engine integrate gate", "engine", "integrate", expect=1, issue="CHECKPOINT_REQUIRED")
        integrate_hook(call, root, f"FF {tag} trunk records the engine checkpoint", runs, "engine")
        commit(root, "engine checkpoint")
        gate(call, root, f"FF {tag} the engine chain passes alone", "engine", "integrate")
        gate(call, root, f"FF {tag} the viewer chain is independent", "viewer", "integrate", expect=1, issue="CHECKPOINT_REQUIRED")
        integrate_hook(call, root, f"FF {tag} trunk records the viewer checkpoint", runs, "viewer")
        commit(root, "viewer checkpoint")
        for branch in order:
            git(root, *MERGE, branch)
        issues = call(f"FF {tag} merged chains check", "check")["issues"]
        check(f"FF {tag} no DECISION_FORK", "DECISION_FORK" not in {i["code"] for i in issues}, str(issues))
        for component in ("engine", "viewer"):
            gate(call, root, f"FF {tag} {component} integrate gate after the merge", component, "integrate")
        states[tag] = hooks(call, root, f"FF {tag} flow section after the merge")
        check(f"FF {tag} every hook is done", all(row[1] == "done" for row in states[tag].values()) and len(states[tag]) == 4,
              str(states[tag]))
        subjects = call(f"FF {tag} subjects", "inspect", "--change", "CHG-001")["data"]["flow"]["stages"]
        done = {r["stage"]: r for r in subjects}["integrate"]["components"]
        check(f"FF {tag} each hook subject is its own run candidate",
              all(done[c]["hook"]["subject"] == runs[c]["candidate"]["inputs_digest"] for c in ("engine", "viewer")), str(done))
    check("FF derived hook state is identical across merge orders", states["left-right"] == states["right-left"], str(states))

    # 3. A flow edited on a branch is not agreed by merging it.
    root, base, call, runs = prepared("c2-flow-edit")
    trunk = git(root, "rev-parse", "HEAD")
    edit = workspace / "flow-edit"
    git(root, "worktree", "add", "-qb", "flow-edit", str(edit), trunk)
    declare_hook(edit, "handoff", declared={"CR-008": "QA can take the integrated change."}, on_reject="defer")
    commit(edit, "edit the flow on a branch")
    git(root, *MERGE, "flow-edit")
    blocked = gate(call, root, "FF unagreed flow edit blocks the implement gate", "engine", "implement", expect=1, issue="FOUNDATION_INCOMPLETE")
    check("FF the blocked gate reports the changed flow reference",
          any(i["entity"] == "flow" and i["code"] == "FOUNDATION_INCOMPLETE" for i in blocked["issues"][0]["actual"]), str(blocked["issues"]))
    call("FF the verify path is also blocked by the unagreed flow", "run", "verify", "CHG-001", "--component", "engine",
         "--base", base, *PRODUCER, expect=1, issue="FOUNDATION_INCOMPLETE")
    stale = call("FF the generated view is stale after the merge", "check")
    check("FF stale flow view warning", [(i["code"], i["severity"]) for i in stale["issues"]] == [("FLOW_VIEW_STALE", "warning")],
          str(stale["issues"]))
    call("FF re-agreement evaluates the declared criteria", "foundation", "agree", "--ref", "flow", *FLOW_ACTOR, *criteria(root, "foundation"))
    gate(call, root, "FF re-agreed flow reopens the implement gate", "engine", "implement")
    persists = call("FF the stale view persists until written", "check")
    check("FF agreement alone leaves the view warning", [i["code"] for i in persists["issues"]] == ["FLOW_VIEW_STALE"], str(persists["issues"]))
    call("FF views --write refreshes the flow view", "views", "--write")
    after = call("FF check is clean once agreed and regenerated", "check")
    check("FF no warning remains", after["issues"] == [], str(after["issues"]))


# ---- FL (M-34): agent sessions, citations, gate demands, storage policies and flow learning ----

SESSION_TRANSCRIPT = b"user: do the fixture work\nassistant: done\n"
SESSION_IGNORED = {"FLOW_VIEW_STALE", "SESSION_REDACTION_EMPTY"}  # Expected warnings of these fixtures.


def fl_caller(root, invoke, check):
    """call(label, *args, expect, issue, recorded, project) -> payload; a rejection writes nothing unless `recorded`."""
    def call(label, *args, expect=0, issue=None, recorded=False, project=None):
        project = project or root
        before = tree(project)
        result = invoke(["--project", str(project), "--json", *map(str, args)])
        check(label, result.returncode == expect, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        check(label + ": JSON envelope", payload["ok"] == (expect == 0), result.stdout)
        if issue:
            check(f"{label}: issue {issue}", issue in [i["code"] for i in payload["issues"]], result.stdout)
        if expect in (1, 2, 3) and not recorded:
            check(label + ": rejection preserves bytes/modes", before == tree(project), result.stdout)
        return payload
    return call


def session_importer(call, folder, prefix):
    """record(label, stage, role, **scope) imports an agent session through the public CLI and returns its EVD ID."""
    folder.mkdir(parents=True, exist_ok=True)
    count = [0]

    def record(label, stage, role, *, content=SESSION_TRANSCRIPT, host=None, expect=0, issue=None, **scope):
        count[0] += 1
        meta = {"model_schema": 2, "host": "claude-code", "host_session_id": host or f"{prefix}-{count[0]}",
                "actor": "Fixture agent", "role": role, "model": "fixture-model", "started_at": "2026-01-31T09:00:00Z",
                "ended_at": "2026-01-31T09:30:00Z", "stage": stage, **scope}
        meta_file, transcript = folder / f"meta-{count[0]}.json", folder / f"session-{count[0]}.jsonl"
        put_json(meta_file, meta)
        transcript.write_bytes(content)
        payload = call(label, "evidence", "record", "--kind", "agent-session", "--file", meta_file, "--transcript", transcript,
                       expect=expect, issue=issue)
        return payload["data"]["evidence"]["id"] if not expect else payload
    return record


def remaining_issues(call, label):
    """`check` issues except the warnings these fixtures expect (flow view staleness, redaction without secrets)."""
    return [i for i in call(label, "check")["issues"] if i["code"] not in SESSION_IGNORED]


def session_lifecycle(workspace, invoke, check):
    """FL seeded flow, unrelaxed: every AI stage requires sessions and each gate demands exactly its own.

    A fresh project keeps the shipped flow (session_evidence required on every AI stage). Each gate is first
    observed rejecting with SESSION_REQUIRED naming the stage, then passes once that session is imported. The
    viewer component is user-facing: only its implement gate demands a design session. Stops at the final
    release gate; the caller continues with the release record when it has a remote.
    """
    workspace = workspace / "fl-lifecycle"
    workspace.mkdir(parents=True)
    root, names = workspace / "consumer with spaces", ("engine", "viewer")
    root.mkdir()
    git(root, "init", "-qb", "main")
    lines = ['schema = 3', 'name = "FL synthetic consumer"', 'trunk_ref = "refs/heads/main"']
    for name in names:
        inline = "{" + ", ".join(f"{k}={json.dumps(v)}" for k, v in {
            "id": "unit", "argv": [sys.executable, "src/check.py"], "cwd": ".", "timeout_seconds": 5,
            "acceptance_ids": ["AC-001"]}.items()) + "}"
        lines.extend([f'[components.{name}]', 'repo = "."', f'user_facing = {str(name == "viewer").lower()}',
                      'target_ref = "refs/remotes/fixture/main"', 'inputs = ["src/**"]', 'generated = ["build/**"]',
                      'excluded = ["private.env", "docs/design.md"]', f'verification = [{inline}]'])
    lines.extend(["[review]", "enabled = false"])
    config = workspace / "profile.toml"
    config.write_text("\n".join(lines) + "\n")
    result = invoke(["--json", "init", str(root), "--profile", str(config)])
    check("FL lifecycle project initializes", result.returncode == 0, result.stdout + result.stderr)
    flow_text = (root / ".roclec/flow.toml").read_text(encoding="utf-8")
    stage_lines = [line for line in flow_text.splitlines() if line.startswith("session_evidence")]
    check("FL seeded flow requires sessions on every AI stage", stage_lines == ['session_evidence = "required"'] * 9,
          str(stage_lines))
    call = fl_caller(root, invoke, check)
    record = session_importer(call, workspace / "inputs", "fl")
    (root / "docs/reference.md").write_text("# Synthetic foundation\n\nFixture data.\n", encoding="utf-8")
    (root / "docs/design.md").write_text("# Synthetic design\n\nFixture data.\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src/check.py").write_text('from pathlib import Path\nassert Path("src/value.txt").read_text() == "saved\\n"\nprint("checked AC-001")\n')
    (root / "src/value.txt").write_text("saved\n")
    (root / ".gitignore").write_text(".roclec/runtime/\nbuild/\nprivate.env\n")

    def demand(label, *args, stage, entity=None, **kwargs):
        """The gate rejects with SESSION_REQUIRED naming `stage` (and the scope to import)."""
        issue = call(label, *args, expect=1, issue="SESSION_REQUIRED", **kwargs)["issues"][0]
        check(label + ": expected stage and scope", issue["expected"] == stage and (entity is None or issue["entity"] == entity)
              and "evidence record --kind agent-session" in issue["remediation"], str(issue))
        return issue

    # Foundation: each reference needs a foundation session whose subject is that reference.
    refs = ["architecture", "context", "engineering", "principles", "stack", "verification"]
    for role in refs:
        call(f"FL register {role}", "reference", "add", role, "--path", "docs/reference.md",
             "--component", "engine", "--component", "viewer", "--role", role)
    call("FL register design (user-facing components only)", "reference", "add", "design", "--path", "docs/design.md",
         "--component", "viewer", "--role", "design")
    call("FL register flow", "reference", "add", "flow", "--path", ".roclec/flow.toml", "--role", "process",
         "--component", "engine", "--component", "viewer")
    owner = ("--actor", "Fixture owner", "--reason", "Synthetic human decision")
    order, sessions = ["flow", *refs, "design"], {}
    for index, ref in enumerate(order):
        agree = ("foundation", "agree", "--ref", ref, *owner, *criteria(root, "foundation"))
        demand(f"FL agree {ref} needs a foundation session", *agree, stage="foundation", entity=ref)
        if index:  # A session of an earlier reference does not satisfy this one, nor may the agreement cite it.
            call(f"FL agree {ref} cannot cite another subject's session", *agree, "--session", sessions[order[index - 1]],
                 expect=2, issue="INVALID_REFERENCE")
        session = sessions[ref] = record(f"FL import the {ref} foundation session", "foundation", "coordinator", subject=ref)
        decision = call(f"FL agree {ref} with its session", *agree, "--session", session)["data"]["decision"]
        check(f"FL {ref} agreement records the session", decision["sessions"] == [session], str(decision))
    base = commit(root)

    # Define: the first bundle cites the define session recorded before the change was imported.
    define = record("FL import the CHG-001 define session before the change exists", "define", "specifier", change_id="CHG-001")
    source = workspace / "bundle"
    change = bundle(source, components=names)
    change["semantic"]["sessions"] = [define]
    change["proposal_digest"] = digest({k: change[k] for k in ("id", "kind", "semantic")})
    put_json(source / "change.json", change)
    call("FL seal the first bundle citing its define session", "change", "seal", source)
    call("FL import the first bundle", "change", "new", "--file", source / "change.json")
    proposal = json.loads((source / "change.json").read_text())
    check("FL imported bundle keeps its cited session", proposal["semantic"]["sessions"] == [define], str(proposal["semantic"]))
    # A second change imported without its define session shows the approve gate demanding one.
    other = workspace / "second-bundle"
    bundle(other, change_id="CHG-002", components=("engine",), kind="refactor")
    call("FL import a second change without sessions", "change", "new", "--file", other / "change.json")
    demand("FL approve gate demands the define session", "check", "--change", "CHG-002", "--gate", "approve",
           stage="define", entity="CHG-002")
    other_define = record("FL import the CHG-002 define session", "define", "specifier", change_id="CHG-002")
    call("FL approve gate passes with the define session", "check", "--change", "CHG-002", "--gate", "approve")
    check("FL other change's session does not count", define != other_define, "")
    approved = call("FL approve cites the define session", "change", "approve", "CHG-001", "--digest", proposal["proposal_digest"],
                    *owner, *criteria(root, "approve"), "--session", define)["data"]["decision"]
    check("FL approval records the session", approved["sessions"] == [define], str(approved))
    for name in names:
        call(f"FL plan {name} release", "release", "plan", name, "v1.0.0", "--change", "CHG-001")
    commit(root)

    # Plan and design: the implement gate demands plan for every component, design only for the user-facing one.
    gate = ("check", "--change", "CHG-001")
    demand("FL engine implement gate demands the plan session", *gate, "--component", "engine", "--gate", "implement",
           stage="plan", entity="CHG-001/engine")
    plan = record("FL import the plan session (no component)", "plan", "implementer", change_id="CHG-001")
    call("FL engine implement gate passes without a design session", *gate, "--component", "engine", "--gate", "implement")
    demand("FL viewer implement gate demands a design session", *gate, "--component", "viewer", "--gate", "implement",
           stage="design", entity="CHG-001/viewer")
    record("FL a design session of the other component does not count", "design", "coordinator", change_id="CHG-001",
           component="engine")
    demand("FL viewer still demands its own design session", *gate, "--component", "viewer", "--gate", "implement",
           stage="design", entity="CHG-001/viewer")
    record("FL import the viewer design session", "design", "coordinator", change_id="CHG-001", component="viewer")
    call("FL viewer implement gate passes with its design session", *gate, "--component", "viewer", "--gate", "implement")
    call("FL start the engine implementation citing the plan session", "change", "start", "CHG-001", "--component", "engine",
         "--actor", "Synthetic maintainer", "--session", plan)

    # Implement: the verify gate demands the implementation session; the final run cites it.
    producer = ("--role", "implementer", "--context", "synthetic implementer session")
    first = call("FL first run without a cited session", "run", "verify", "CHG-001", "--component", "engine", "--base", base,
                 *producer)["data"]["run"]
    commit(root)
    demand("FL verify gate demands the implement session", *gate, "--component", "engine", "--gate", "verify",
           stage="implement", entity="CHG-001/engine")
    implement = record("FL import the engine implement session", "implement", "implementer", change_id="CHG-001", component="engine")
    run = call("FL run cites the implement session", "run", "verify", "CHG-001", "--component", "engine", "--base", base,
               *producer, "--session", implement)["data"]["run"]
    check("FL run stores producer.sessions", run["producer"]["sessions"] == [implement] and run["id"] != first["id"], str(run["producer"]))
    observation = workspace / "observation.json"
    put_json(observation, {"model_schema": 2, "kind": "manual", "change_id": "CHG-001", "component": "engine", "run_id": run["id"],
                           "candidate_digest": run["candidate"]["inputs_digest"], "actor": "Synthetic observer",
                           "context": "Observation fixture", "outcome": "pass", "acceptance_ids": ["AC-001"],
                           "checks": ["Observed test"], "limitations": [], "findings": [], "sessions": [implement]})
    report = call("FL evidence cites the implement session", "evidence", "record", "--file", observation)["data"]["evidence"]
    check("FL evidence stores its session", report["sessions"] == [implement], str(report))
    commit(root)
    call("FL verify gate passes", *gate, "--component", "engine", "--gate", "verify")

    # Verify and integrate: the integrate gate demands the verify session; the release gate the integrate session.
    demand("FL integrate gate demands the verify session", *gate, "--component", "engine", "--gate", "integrate",
           stage="verify", entity="CHG-001/engine")
    out = workspace / "integration.json"
    demand("FL integrate prepare demands the verify session", "integrate", "prepare", "CHG-001", "--component", "engine",
           "--run", run["id"], "--out", out, stage="verify")
    check("FL rejected prepare exports no plan", not out.exists(), "")
    record("FL import the engine verify session", "verify", "implementer", change_id="CHG-001", component="engine")
    commit(root)
    call("FL integrate gate passes", *gate, "--component", "engine", "--gate", "integrate")
    call("FL integrate prepare", "integrate", "prepare", "CHG-001", "--component", "engine", "--run", run["id"], "--out", out)
    call("FL integrate apply", "operation", "apply", out)
    commit(root)
    release = ("check", "--gate", "release", "--component", "engine", "--release", "v1.0.0")
    demand("FL release gate demands the integrate session of each member", *release, stage="integrate", entity="CHG-001/engine")
    record("FL import the engine integrate session", "integrate", "coordinator", change_id="CHG-001", component="engine")
    final = call("FL final release run", "run", "verify", "--release", "v1.0.0", "--component", "engine", "--base", base,
                 "--role", "coordinator", "--context", "Synthetic release run")["data"]["run"]
    commit(root)
    call("FL release gate passes with the sessions each gate demanded", *release)
    check("FL lifecycle check is clean", remaining_issues(call, "FL lifecycle check") == [], "")
    return {"root": root, "base": base, "call": call, "record": record, "run": final, "workspace": workspace}


def session_citation_scenarios(workspace, invoke, check):
    """FL `--session` is stored on rejections, checkpoints (prototype and hook), cancellations and FUT decisions."""
    workspace = workspace / "fl-citations"
    root, base = setup(workspace, invoke, names=("engine",))
    call = fl_caller(root, invoke, check)
    record = session_importer(call, workspace / "inputs", "cite")
    owner = ("--actor", "Fixture owner", "--reason", "Synthetic human decision")
    stored = lambda decision: json.loads((root / f".roclec/decisions/{decision['id']}.json").read_text())  # noqa: E731

    def cited(label, decision, *sessions):
        check(label + ": decision stores its sessions", decision["sessions"] == sorted(sessions)
              and stored(decision)["sessions"] == sorted(sessions), str(decision))

    first = record("FL define session of CHG-001", "define", "specifier", change_id="CHG-001")
    corrections = workspace / "corrections.json"
    put_json(corrections, [{"id": "R-1", "description": "Explain the empty state"}])
    revise = ("--consequence", "revise", "--corrections", corrections)
    for change_id in ("CHG-002", "CHG-003"):
        folder = workspace / f"bundle-{change_id}"
        bundle(folder, change_id=change_id, components=("engine",), kind="refactor")
        call(f"FL import {change_id}", "change", "new", "--file", folder / "change.json")
    second, third = (record(f"FL define session of {c}", "define", "specifier", change_id=c) for c in ("CHG-002", "CHG-003"))
    digest_2 = json.loads((workspace / "bundle-CHG-002/change.json").read_text())["proposal_digest"]
    call("FL a rejection cannot cite another change's session", "reject", "change", "CHG-002", "--digest", digest_2, *owner,
         *revise, *criteria(root, "approve", "rejected"), "--session", first, expect=2, issue="INVALID_REFERENCE")
    rejection = call("FL reject a change citing its session", "reject", "change", "CHG-002", "--digest", digest_2, *owner, *revise,
                     *criteria(root, "approve", "rejected"), "--session", second)["data"]["decision"]
    cited("FL change rejection", rejection, second)
    canceled = call("FL cancel a change citing its session", "change", "cancel", "CHG-003", *owner, "--session", third)["data"]["decision"]
    cited("FL change cancellation", canceled, third)

    design = record("FL design session of the prototype", "design", "coordinator", change_id="CHG-001", component="engine")
    prototype = root / "mockups/preview.html"
    prototype.parent.mkdir()
    prototype.write_bytes(b"<h1>Preview</h1>\n")
    pin = file_hash(prototype.read_bytes())
    approved = call("FL prototype checkpoint citing a session", "checkpoint", "mockups/preview.html", "--digest", pin, *owner,
                    "--outcome", "approved", *criteria(root, "design"), "--session", design)["data"]["decision"]
    cited("FL prototype checkpoint", approved, design)
    refused = call("FL reject the prototype citing a session", "reject", "prototype", "mockups/preview.html", "--digest", pin,
                   *owner, *revise, *criteria(root, "design", "rejected"), "--session", design)["data"]["decision"]
    cited("FL prototype rejection", refused, design)

    declare_hook(root, "pre-implement")
    call("FL agree the flow with a declared hook", "foundation", "agree", "--ref", "flow", *owner, *criteria(root, "foundation"))
    proposal = json.loads((root / ".roclec/changes/CHG-001/change.json").read_text())["proposal_digest"]
    hook = call("FL hook checkpoint citing a session", "checkpoint", "CHG-001", "--hook", "pre-implement", "--component", "engine",
                "--digest", proposal, *owner, "--outcome", "approved", "--session", first)["data"]["decision"]
    cited("FL hook checkpoint", hook, first)

    fut = workspace / "fut.json"
    put_json(fut, {"model_schema": 2, "id": "FUT-001", "finding": "Review later", "impact": "Rework", "questions": [],
                   "source": {"location": "request", "locator": "FL fixture"}})
    call("FL capture a FUT", "fut", "capture", "--file", fut)
    decided = call("FL decide a FUT citing a session", "fut", "decide", "FUT-001", "--outcome", "discarded", *owner,
                   "--session", first)["data"]["decision"]
    cited("FL FUT decision", decided, first)
    check("FL citations leave a clean check", remaining_issues(call, "FL citations check") == [], "")


def session_review_scenarios(workspace, invoke, check):
    """FL a required review stage binds the review context to the reviewer's session and rejects self-review."""
    workspace = workspace / "fl-review"
    root, base = setup(workspace, invoke, names=("engine",), review={"enabled": True})
    call = fl_caller(root, invoke, check)
    record = session_importer(call, workspace / "inputs", "review")
    flow = root / ".roclec/flow.toml"
    text = flow.read_text(encoding="utf-8")
    start = text.index("[stages.review]\n")
    flow.write_text(text[:start] + text[start:].replace('session_evidence = "optional"', 'session_evidence = "required"', 1), encoding="utf-8")
    call("FL agree the flow requiring review sessions", "foundation", "agree", "--ref", "flow", "--actor", "Fixture owner",
         "--reason", "Review sessions are required", *criteria(root, "foundation"))
    commit(root)
    producer = record("FL implementer session on the shared host", "implement", "implementer", host="shared-host",
                      change_id="CHG-001", component="engine")
    run = call("FL run cites the implementer session", "run", "verify", "CHG-001", "--component", "engine", "--base", base,
               *PRODUCER, "--session", producer, expect=1, issue="REVIEW_REQUIRED", recorded=True)["data"]["run"]
    policy = call("FL review policy", "inspect", "--change", "CHG-001")["data"]["review_policy"]
    reviews = workspace / "reviews"
    reviews.mkdir()

    def review(context):
        path = reviews / f"review-{len(list(reviews.iterdir()))}.json"
        put_json(path, {"model_schema": 2, "kind": "independent-review", "change_id": "CHG-001", "component": "engine",
                        "run_id": run["id"], "candidate_digest": run["candidate"]["inputs_digest"], "actor": "Fixture reviewer",
                        "role": "reviewer", "context": context, "policy_id": policy["id"], "outcome": "ready",
                        "acceptance_ids": ["AC-001"], "checks": ["Reviewed"], "limitations": [], "findings": [], "resolutions": []})
        return path

    call("FL free-text review context is refused when sessions are required", "evidence", "record", "--file",
         review("Synthetic reviewer session"), expect=2, issue="SESSION_REQUIRED")
    shared = record("FL reviewer session on the producer's host", "review", "reviewer", host="shared-host",
                    change_id="CHG-001", component="engine")
    call("FL review sharing the producer's host session is self-review", "evidence", "record", "--file", review(shared),
         expect=1, issue="SELF_REVIEW_DECLARED")
    call("FL review citing the producer's own session is refused", "evidence", "record", "--file", review(producer),
         expect=2, issue="INVALID_REFERENCE")
    reviewer = record("FL independent reviewer session", "review", "reviewer", host="reviewer-host",
                      change_id="CHG-001", component="engine")
    stored = call("FL independent review cites its session", "evidence", "record", "--file", review(reviewer))["data"]["evidence"]
    check("FL review context is the reviewer session", stored["context"] == reviewer, str(stored))
    call("FL verify gate passes after the independent review", "check", "--change", "CHG-001", "--component", "engine",
         "--gate", "verify")
    check("FL review scenario check is clean", remaining_issues(call, "FL review check") == [], "")


def session_storage_scenarios(workspace, invoke, check):
    """FL storage policies: redacted versioned copies, local-only storage and the quota, through the public CLI."""
    workspace = workspace / "fl-storage"
    root, base = setup(workspace, invoke, names=("engine",))
    call = fl_caller(root, invoke, check)
    record = session_importer(call, workspace / "inputs", "storage")
    profile = root / ".roclec/project.toml"
    secret = "s3cret-session-value-91"
    content = (f"user: deploy with {secret}\nassistant: token tok-4821 used; ok\ntool: echo {secret}\n").encode()
    text = profile.read_text(encoding="utf-8")
    profile.write_text(text.replace('trunk_ref = "refs/heads/main"\n',
                                    'trunk_ref = "refs/heads/main"\nredact_patterns = ["tok-[0-9]+", "s3cret-[a-z0-9-]+"]\n', 1), encoding="utf-8")

    def outside_runtime():
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()
                and ".git" not in p.relative_to(root).parts and not p.relative_to(root).as_posix().startswith(".roclec/runtime/")}

    redacted = record("FL import a transcript under versioned-redacted", "implement", "implementer", content=content,
                      change_id="CHG-001", component="engine")
    stored = json.loads((root / f".roclec/evidence/{redacted}.json").read_text())
    check("FL redaction counts every replacement", stored["transcript"]["storage"] == "versioned-redacted"
          and stored["transcript"]["redactions"] == 3, str(stored["transcript"]))
    copy = (root / f".roclec/evidence/{redacted}.session").read_bytes()
    check("FL versioned copy replaces secrets", copy == content.replace(secret.encode(), b"[REDACTED]").replace(b"tok-4821", b"[REDACTED]"),
          copy.decode())
    check("FL no versioned file shows a secret", all(secret.encode() not in data and b"tok-4821" not in data
                                                     for data in outside_runtime().values()), "")
    original = root / f".roclec/runtime/sessions/{redacted}/session-1.jsonl"
    check("FL the untracked original stays byte for byte", original.read_bytes() == content, str(original))
    check("FL redacted storage keeps check clean", remaining_issues(call, "FL redacted check") == [], "")

    profile.write_text(profile.read_text(encoding="utf-8").rstrip("\n") + '\n[sessions]\nstorage = "local"\nquota_bytes = 16\n', encoding="utf-8")
    before = outside_runtime()
    sessions_before = sorted(p.name for p in (root / ".roclec/runtime/sessions").iterdir())
    call("FL a transcript over the quota is rejected", "evidence", "record", "--kind", "agent-session", "--file",
         workspace / "inputs/meta-1.json", "--transcript", workspace / "inputs/session-1.jsonl", expect=2, issue="SESSION_QUOTA_EXCEEDED")
    check("FL the rejected import wrote nothing", outside_runtime() == before and sorted(
        p.name for p in (root / ".roclec/runtime/sessions").iterdir()) == sessions_before, "")
    local = record("FL a transcript at the quota under local storage", "implement", "implementer", content=b"x" * 16,
                   change_id="CHG-001", component="engine")
    stored = json.loads((root / f".roclec/evidence/{local}.json").read_text())
    check("FL local storage versions no copy", stored["transcript"]["storage"] == "local"
          and stored["transcript"]["versioned_sha256"] is None and not (root / f".roclec/evidence/{local}.session").exists(), str(stored))
    check("FL local storage keeps the original untracked", (root / f".roclec/runtime/sessions/{local}/session-2.jsonl").read_bytes() == b"x" * 16, "")
    check("FL local storage keeps check clean", remaining_issues(call, "FL local check") == [], "")


def flow_learning_scenarios(workspace, invoke, check):
    """FL process FUT -> agreed flow revision -> promotion -> deterministic flow view and preserved retrospective."""
    workspace = workspace / "fl-learning"
    root, base = setup(workspace, invoke)
    call = fl_caller(root, invoke, check)
    owner = ("--actor", "Fixture owner", "--reason", "Approve later in the flow")
    fut = workspace / "fut.json"
    put_json(fut, {"model_schema": 2, "id": "FUT-001", "source": {"location": "retro", "locator": "FL fixture"},
                   "finding": "The approve gate blocks too early", "impact": "Rework", "questions": [], "scope": "process"})
    call("FL capture a process FUT", "fut", "capture", "--file", fut)
    flow = root / ".roclec/flow.toml"
    flow.write_text(flow.read_text(encoding="utf-8") + "\n# Adjusted after FUT-001.\n", encoding="utf-8")
    agreement = call("FL agree the adjusted flow citing the FUT", "foundation", "agree", "--ref", "flow", *owner,
                     *criteria(root, "foundation"), "--fut", "FUT-001")["data"]["decision"]
    check("FL agreement records the process FUT", agreement["futs"] == ["FUT-001"], str(agreement))
    call("FL promote the FUT to the agreement that addresses it", "fut", "decide", "FUT-001", "--outcome", "promoted",
         *owner, "--target", agreement["id"])
    inspected = call("FL inspect the FUT", "inspect", "--fut", "FUT-001")["data"]
    check("FL the FUT is addressed by the flow agreement", inspected["scope"] == "process" and inspected["status"] == "promoted"
          and inspected["addressed_by"] == [{"decision": agreement["id"], "flow": agreement["sources"]["flow"],
                                             "reason": "Approve later in the flow", "actor": "Fixture owner"}], str(inspected))
    stale = [i["code"] for i in call("FL the view is stale after new records", "check")["issues"]]
    check("FL records make the flow view stale", "FLOW_VIEW_STALE" in stale, str(stale))
    call("FL views without --write refuse a stale view", "views", expect=1, issue="VIEW_STALE")
    view = root / "docs/flow.md"
    call("FL views --write regenerates the flow view", "views", "--write")
    first = view.read_bytes()
    row = next((line for line in first.decode().splitlines() if line.startswith(f"| `{agreement['id']}`")), "")
    check("FL view shows the revision with its FUT and reason", "Approve later in the flow" in row
          and "FUT-001 (process): The approve gate blocks too early" in row and agreement["sources"]["flow"] in row, row)
    written = call("FL second views --write", "views", "--write")["data"]["written"]
    check("FL two consecutive views --write are byte-identical", view.read_bytes() == first and written == [], str(written))
    check("FL the regenerated view is current", [i for i in call("FL check after views", "check")["issues"]
                                                if i["code"] == "FLOW_VIEW_STALE"] == [], "")

    retro = root / "docs/flow-retro.md"
    check("FL init seeded the flow retrospective", retro.is_file() and retro.read_bytes().startswith(b"# Flow retrospective"), "")
    retro.write_text("# Our retro\n\nThe approve gate was too early.\n", encoding="utf-8")
    edited = retro.read_bytes()
    call("FL skills refresh", "skills")
    check("FL a refresh preserves the edited retrospective", retro.read_bytes() == edited, "")
    manifest = json.loads((root / ".roclec/installation.json").read_text())
    check("FL the retrospective is not a managed file", "docs/flow-retro.md" not in manifest["managed"], str(manifest["managed"])[:200])


def session_scenarios(workspace, invoke, check):
    """Every FL consumer scenario that needs no remote; the release record is covered in C3."""
    session_lifecycle(workspace, invoke, check)
    session_citation_scenarios(workspace, invoke, check)
    session_review_scenarios(workspace, invoke, check)
    session_storage_scenarios(workspace, invoke, check)
    flow_learning_scenarios(workspace, invoke, check)
