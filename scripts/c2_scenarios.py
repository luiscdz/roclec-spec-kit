"""Real public C2 operations on disposable Git consumers, shared with the wheel harness."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import shutil

try:
    from .c1_scenarios import bundle, foundation, put_json, tree, snapshot, digest, seed_publication, seed_current
except ImportError:
    from c1_scenarios import bundle, foundation, put_json, tree, snapshot, digest, seed_publication, seed_current


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


def setup(workspace, invoke, *, names=("engine", "viewer"), coverage=True, check_code=None, timeout=5):
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
                 ("change", "approve", "CHG-001", "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "synthetic test approval")):
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
                  "findings": [{"id": "F-001", "description": "Stable historical finding"}]}
        if kind == "independent-review":
            record.update(policy_id=policy["id"], role="reviewer")
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
    report("ready")
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
    call("C2 explicitly approve pending revision", "change", "approve", "CHG-001", "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "Clarify pending participant")
    call("C2 rebind pending release membership only", "release", "plan", "viewer", "v1.0.0", "--change", "CHG-001")
    viewer = call("C2 fresh evidence for pending intent", "run", "verify", "CHG-001", "--component", "viewer", "--base", base, *PRODUCER)["run"]
    commit(root, "record first integration")
    second_plan = workspace / "viewer-integration.json"
    call("I-011 prepare remaining component", "integrate", "prepare", "CHG-001", "--component", "viewer", "--run", viewer["id"], "--out", second_plan)
    call("I-011 integrate remaining component", "operation", "apply", second_plan)
    state = call("I-011 inspect fully integrated change", "inspect", "--change", "CHG-001")
    check("I-011 all participants integrated", state["status"] == "integrated")
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


def prepared_fixture(workspace, invoke):
    root, base = setup(workspace, invoke, names=("engine",))
    prefix = ["--project", str(root), "--json"]
    result = invoke([*prefix, "run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER])
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    run = json.loads(result.stdout)["data"]["run"]
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
        must("change", "approve", change_id, "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "synthetic evolution")
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
    must("change", "approve", "CHG-002", "--digest", record["proposal_digest"], "--actor", "fixture", "--reason", "Restore historical contract")
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
