"""Viewer scenarios on real consumer projects, shared by unittest and the installed-wheel harness.

All writes go through the public CLI (``invoke``). Every read goes through ``fetch(root, path)``,
which returns ``(status, payload)`` from the viewer API, so the same assertions run against the
Flask test client and against a ``roclec view`` process from the installed wheel. The CLI result
is the oracle for gate diagnostics; the viewer must reproduce it.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

try:
    from .c1_scenarios import digest, put_json, tree
    from .c2_scenarios import PRODUCER, commit, git, setup
    from .c3_scenarios import combined_and_fix_scenarios
except ImportError:
    from c1_scenarios import digest, put_json, tree
    from c2_scenarios import PRODUCER, commit, git, setup
    from c3_scenarios import combined_and_fix_scenarios

CAP = "CAP-001"


def cli(invoke, root, *args, expect=0):
    result = invoke(["--project", str(root), "--json", *map(str, args)])
    if result.returncode != expect:
        raise AssertionError(f"{args}: {result.stdout}{result.stderr}")
    return json.loads(result.stdout)


def planning_fixture(workspace, invoke, *, docs=None):
    """Two components share REQ-001; every member of engine v1.0.0 is integrated, the final gate is blocked.

    Engine's final run exists, a manual observation was superseded, and an independent review
    is required but unfavorable. Viewer is integrated too but has no final run.
    """
    root, base = setup(workspace, invoke)
    if docs:
        # Documents the consumer declares as inputs, so they never make a candidate unclassified.
        config = root / ".roclec/project.toml"
        config.write_text(config.read_text().replace('inputs = ["src/**"]', 'inputs = ["src/**", "docs/**", "specs/**"]'))
        for relative, body in docs.items():
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_text(body, encoding="utf-8")
        base = commit(root)
    for component in ("engine", "viewer"):
        run = cli(invoke, root, "run", "verify", "CHG-001", "--component", component, "--base", base, *PRODUCER)["data"]["run"]
        commit(root)
        plan = workspace / f"integrate-{component}.json"
        cli(invoke, root, "integrate", "prepare", "CHG-001", "--component", component, "--run", run["id"], "--out", plan)
        cli(invoke, root, "operation", "apply", plan)
        commit(root)
    cli(invoke, root, "review", "policy", "--change", "CHG-001", "--enabled", "true", "--actor", "fixture user", "--reason", "Review final release")
    commit(root)
    final = cli(invoke, root, "run", "verify", "--release", "v1.0.0", "--component", "engine", "--base", base, *PRODUCER, expect=1)["data"]["run"]
    commit(root)
    policy = cli(invoke, root, "inspect", "--release", "v1.0.0", "--component", "engine")["data"]["review_policy"]
    reports = []
    for kind, actor, outcome in (("manual", "observer", "fail"), ("manual", "observer", "pass"),
                                 ("independent-review", "R1", "ready"), ("independent-review", "R2", "changes-needed")):
        report = {"model_schema": 2, "kind": kind, "change_id": None, "release": {"component": "engine", "version": "v1.0.0"},
                  "component": "engine", "run_id": final["id"], "candidate_digest": final["candidate"]["inputs_digest"], "actor": actor,
                  "context": "Structural fixture; no product acceptance", "outcome": outcome, "acceptance_ids": ["AC-001"],
                  "checks": ["Synthetic observation"], "limitations": ["Fixture only"], "findings": []}
        if kind == "independent-review":
            report.update(policy_id=policy["id"], role="reviewer")
        file = workspace / f"report-{len(reports)}.json"
        put_json(file, report)
        reports.append(cli(invoke, root, "evidence", "record", "--file", file)["data"]["evidence"]["id"])
        commit(root)
    return root, base, final, reports


def forge_unfinished_run(root, template_run):
    """A run that was reserved but never finalized: same candidate, new identity, no manifest."""
    started = json.loads((root / f".roclec/runs/{template_run}/start.json").read_text())
    new_id = "RUN-" + "7ZZZZZZZZZZZZZZZZZZZZZZZZZ"
    started.update(id=new_id, supersedes=[template_run])
    started.pop("digest")
    started["digest"] = digest(started)
    put_json(root / f".roclec/runs/{new_id}/start.json", started)
    return new_id


def tracked_state(root):
    index = root / ".git/index"
    return {"files": tree(root), "index": index.read_bytes() if index.exists() else b""}


def scenarios(workspace, invoke, check, fetch):
    """Planning, comparison with CLI, read-only behavior, evidence states and reading scope."""
    root, base, final, reports = planning_fixture(workspace / "viewer-planning", invoke)

    def get(path, expect=200):
        status, payload = fetch(root, path)
        check(f"GET {path.split('?')[0]}: HTTP {expect}", status == expect, json.dumps(payload)[:400])
        return payload["data"] if expect == 200 else payload["error"]

    before = tracked_state(root)
    release = get("/api/v1/releases/engine/v1.0.0")
    check("V-001 release lists every member and counts come from the same rows",
          release["total"] == len(release["members"]) == 1 and sum(release["counts"].values()) == release["total"]
          and release["counts"]["integrated"] == 1 and {m["stage"] for m in release["members"]} == {"integrated"})
    cli_gate = cli(invoke, root, "check", "--component", "engine", "--gate", "release", "--release", "v1.0.0", expect=1)
    issue = cli_gate["issues"][0]
    gate = release["gate"]
    check("V-002 all members integrated and final gate blocked, both facts shown", release["counts"]["integrated"] == release["total"] and gate["ok"] is False)
    check("V-002 gate diagnostic equals `check --gate release`",
          (gate["code"], gate["message"], gate["entity"], gate["expected"], gate["actual"], gate["remediation"]) ==
          (issue["code"], issue["message"], issue["entity"], issue["expected"], issue["actual"], issue["remediation"]), json.dumps([gate, issue]))
    check("V-002 REVIEW_REQUIRED stays separate from coverage", gate["code"] == "REVIEW_REQUIRED" and release["policy"]["enabled"] is True)
    inspected = cli(invoke, root, "inspect", "--release", "v1.0.0", "--component", "engine")["data"]
    check("V-003 membership matches inspect", [m["change_id"] for m in release["members"]] == [c["change_id"] for c in inspected["record"]["changes"]]
          and release["status"] == inspected["status"])
    listing = get("/api/v1/releases")["releases"]
    cli_list = cli(invoke, root, "list", "releases")["data"]["releases"]
    check("V-003 release list matches `list releases`",
          [(r["component"], r["version"], r["status"]) for r in listing] == [(r["component"], r["version"], r["status"]) for r in cli_list])
    check("V-004 opening and refreshing never modify the consumer", before == tracked_state(root))

    contract = release["contracts"][0]
    base_query = f"cap={contract['cap']}&revision={contract['revision']}&component=engine&release=v1.0.0"
    req = get(f"/api/v1/requirements/REQ-001?{base_query}")
    check("V-005 two components sharing a requirement show each one's coverage", set(req["coverage"]) == {"engine", "viewer"}
          and req["coverage"]["engine"]["criteria"]["AC-001"]["state"] == "covered"
          and req["coverage"]["viewer"]["criteria"]["AC-001"]["state"] in {"pending", "not-evaluated"}, json.dumps(req["coverage"])[:600])
    engine = req["coverage"]["engine"]
    check("V-006 required review is a separate unfavorable condition, gate not approved",
          engine["review"]["required"] is True and engine["review"]["state"] == "changes-needed" and gate["ok"] is False)
    states = {r["id"]: r["state"] for r in engine["reports"]}
    check("V-006 replaced evidence is distinguished from the current one", states[reports[0]] == "superseded" and states[reports[1]] == "applicable", json.dumps(states))
    report = get(f"/api/v1/evidence/{reports[0]}")
    check("V-006 report names its replacement and is not executed by Roclec", report["state"] == "superseded" and report["superseded_by"] == [reports[1]]
          and report["executed_by_roclec"] is False)
    check("V-007 evidence links back to the criterion", report["criteria"] and report["criteria"][0]["ac"] == "AC-001" and report["criteria"][0]["cap"] == CAP)
    run = get(f"/api/v1/evidence/{final['id']}")
    check("V-007 run is executed by Roclec and exposes only log metadata",
          run["executed_by_roclec"] is True and all(set(c["logs"][k]) == {"size", "complete", "sha256"} for c in run["checks"] for k in ("stdout", "stderr"))
          and "excerpt" not in json.dumps(run) and ".roclec/runtime" not in json.dumps(run))
    check("V-007 check detail resolves", get(f"/api/v1/evidence/{final['id']}/checks/unit")["check"]["id"] == "unit")

    change = get("/api/v1/changes/CHG-001")
    check("V-008 change shows approved revision, per-component stages and affected requirement",
          change["revision"] == change["current_revision"] and set(change["stages"]) == {"engine", "viewer"}
          and change["requirements"][0]["req"] == "REQ-001" and change["requirements"][0]["proposed_revision"])
    check("V-008 foreign component is rejected", get("/api/v1/changes/CHG-001?component=nope", expect=404)["kind"] == "not_found")
    check("V-009 unknown release/change/requirement report not_found",
          all(get(p, expect=404)["kind"] == "not_found" for p in (
              "/api/v1/releases/engine/v9.9.9", "/api/v1/changes/CHG-099", f"/api/v1/requirements/REQ-099?cap={CAP}&revision={contract['revision']}",
              "/api/v1/evidence/RUN-01ARZ3NDEKTSV4RRFFQ69G5FAV")))
    check("V-009 entity outside the requested context is rejected",
          get(f"/api/v1/requirements/REQ-001?{base_query}&change=CHG-001", expect=400)["kind"] == "invalid_query")

    # Unfinished run: reserved but never finalized.
    interrupted = workspace / "viewer-interrupted"
    shutil.copytree(root, interrupted, symlinks=True)
    forged = forge_unfinished_run(interrupted, final["id"])
    status, payload = fetch(interrupted, f"/api/v1/requirements/REQ-001?{base_query}")
    coverage = payload["data"]["coverage"]["engine"]
    check("V-010 interrupted run is distinct from a failed or missing one", status == 200 and coverage["stop"]["code"] == "CANDIDATE_INCOMPLETE"
          and coverage["criteria"]["AC-001"]["state"] == "not-evaluated", json.dumps(coverage)[:500])
    status, payload = fetch(interrupted, f"/api/v1/evidence/{forged}")
    check("V-010 unfinished run is readable", status == 200 and payload["data"]["status"] == "unfinished")
    status, payload = fetch(interrupted, "/api/v1/releases/engine/v1.0.0")
    check("V-010 interrupted final run never reports an approved gate", payload["data"]["gate"]["ok"] is False and payload["data"]["gate"]["code"] == "CANDIDATE_INCOMPLETE")

    # Reading scope and active content.
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs/active.md").write_text("# Active\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1)) ![i](../../outside.png)\n", encoding="utf-8")
    (root / "docs/unique.md").write_text("# Zebra notes\n\nMention of the quokka heuristic only here.\n", encoding="utf-8")
    (workspace / "viewer-planning/outside.md").write_text("# outside\n", encoding="utf-8")
    (root / ".roclec/runtime/logs").mkdir(parents=True, exist_ok=True)
    (root / ".roclec/runtime/logs/raw.md").write_text("# raw log\n", encoding="utf-8")
    link_target = workspace / "viewer-planning/secret.md"
    link_target.write_text("# secret\n", encoding="utf-8")
    (root / "docs/linked.md").symlink_to(link_target)
    tree_paths = json.dumps(get("/api/v1/docs/tree"))
    check("V-011 tree lists documents but never runtime, git or symlinks", "docs/active.md" in tree_paths and "raw.md" not in tree_paths
          and "linked.md" not in tree_paths and ".git" not in tree_paths)
    for hostile in ("../outside.md", "docs/../../outside.md", "/etc/passwd", ".roclec/runtime/logs/raw.md", ".git/config", "docs/linked.md",
                    "docs/%2e%2e/outside.md", "docs\\active.md", ".roclec/current.json"):
        status, _ = fetch(root, "/api/v1/docs/file?path=" + hostile.replace("\\", "%5C"))
        check(f"V-011 path {hostile!r} is rejected", status == 404)
    status, _ = fetch(root, "/api/v1/docs/asset?path=../outside.png")
    check("V-011 asset traversal is rejected", status == 404)
    active = get("/api/v1/docs/file?path=docs/active.md")
    check("V-012 active Markdown is served as inert text", "<script>" in active["content"] and active["path"] == "docs/active.md")
    check("V-013 search by exact REQ opens the entity with its contract revision",
          any(r["type"] == "entity" and r["id"] == "REQ-001" and r["revision"] == contract["revision"] for r in get("/api/v1/search?q=REQ-001")["results"]))
    check("V-013 search by exact AC", any(r["type"] == "entity" and r["id"] == "AC-001" and r["link"]["req"] == "REQ-001" for r in get("/api/v1/search?q=ac-001")["results"]))
    check("V-013 text search finds documents and contract text", any(r["path"] == "docs/unique.md" for r in get("/api/v1/search?q=quokka")["results"] if r["type"] == "doc")
          and any(r["type"] == "entity" for r in get("/api/v1/search?q=single%20line")["results"]))

    # Branch changes: results from the previous branch must not survive.
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "add", "docs")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "docs on main")
    status, state_main = fetch(root, "/api/v1/state")
    git(root, "checkout", "-qb", "feature")
    (root / "docs/unique.md").unlink()
    (root / "docs/branch.md").write_text("# Branch only\n\nThe narwhal heuristic exists on feature.\n", encoding="utf-8")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "add", "-A", "docs")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "feature docs")
    status, state_feature = fetch(root, "/api/v1/state")
    check("V-014 branch change alters the repository state fingerprint", state_main["state_id"] != state_feature["state_id"])
    check("V-014 project reports the new branch", get("/api/v1/project")["branch"] == "feature")
    check("V-014 refreshed index omits results from the previous branch", get("/api/v1/search?q=quokka")["results"] == []
          and any(r.get("path") == "docs/branch.md" for r in get("/api/v1/search?q=narwhal")["results"]))
    git(root, "checkout", "-q", "main")
    check("V-014 returning restores previous results", get("/api/v1/search?q=narwhal")["results"] == []
          and any(r.get("path") == "docs/unique.md" for r in get("/api/v1/search?q=quokka")["results"]))
    status, state_clean = fetch(root, "/api/v1/state")
    (root / "docs/unique.md").write_text("# Zebra notes\n\nMention of the okapi heuristic, uncommitted.\n", encoding="utf-8")
    status, state_dirty = fetch(root, "/api/v1/state")
    check("V-015 uncommitted local edits change the fingerprint", state_clean["state_id"] != state_dirty["state_id"])
    check("V-015 uncommitted text is searchable after refresh", any(r.get("path") == "docs/unique.md" for r in get("/api/v1/search?q=okapi")["results"]))
    return root


def review_attribution_scenarios(workspace, invoke, check, fetch):
    """M-28: the viewer counts a review only when the verify gate would (declared role, distinct contexts)."""
    def engine_review(root, release):
        query = (f"cap={CAP}&revision={release['contracts'][0]['revision']}&component=engine&release=v1.0.0")
        status, payload = fetch(root, f"/api/v1/requirements/REQ-001?{query}")
        check("M-28 requirement read succeeds", status == 200, json.dumps(payload)[:300])
        return payload["data"]["coverage"]["engine"]["review"]

    def strip(root, relative, key):
        path = root / relative
        record = json.loads(path.read_text())
        record.pop(key)
        record.pop("digest")
        record["digest"] = digest(record)
        put_json(path, record)

    root, base, final, reports = planning_fixture(workspace / "viewer-attribution-self", invoke)
    status, payload = fetch(root, "/api/v1/releases/engine/v1.0.0")
    release = payload["data"]
    # R2 becomes favorable too, so the only open question is whether the reviews count.
    policy = cli(invoke, root, "inspect", "--release", "v1.0.0", "--component", "engine")["data"]["review_policy"]
    favorable = {"model_schema": 2, "kind": "independent-review", "change_id": None, "release": {"component": "engine", "version": "v1.0.0"},
                 "component": "engine", "run_id": final["id"], "candidate_digest": final["candidate"]["inputs_digest"], "actor": "R2",
                 "context": "Reviewer session B", "outcome": "ready", "acceptance_ids": ["AC-001"], "checks": ["Synthetic observation"],
                 "limitations": ["Fixture only"], "findings": [], "policy_id": policy["id"], "role": "reviewer"}
    put_json(workspace / "favorable.json", favorable)
    cli(invoke, root, "evidence", "record", "--file", workspace / "favorable.json")
    commit(root)
    check("M-28 attributed independent reviews still show ready", engine_review(root, release)["state"] == "ready")
    rerun = cli(invoke, root, "run", "verify", "--release", "v1.0.0", "--component", "engine", "--base", base,
                "--role", "implementer", "--context", " REVIEWER session b ", expect=1)
    check("M-28 gate rejects the declared self-review", rerun["issues"][0]["code"] == "SELF_REVIEW_DECLARED", json.dumps(rerun["issues"]))
    commit(root)
    review = engine_review(root, release)
    by_actor = {r["id"]: r for r in review["reviews"]}
    check("M-28 a review in the producer's context is not shown as favorable",
          review["state"] != "ready" and any(r["uncounted"] == "self-review-declared" and r["state"] != "applicable" for r in by_actor.values()),
          json.dumps(review)[:500])

    root, base, final, reports = planning_fixture(workspace / "viewer-attribution-history", invoke)
    status, payload = fetch(root, "/api/v1/releases/engine/v1.0.0")
    release = payload["data"]
    for name in ("start.json", "manifest.json"):
        strip(root, f".roclec/runs/{final['id']}/{name}", "producer")
    strip(root, f".roclec/evidence/{reports[2]}.json", "role")
    commit(root)
    review = engine_review(root, release)
    r1 = next(r for r in review["reviews"] if r["id"] == reports[2])
    check("M-28 unattributed history is not shown as favorable",
          review["state"] != "ready" and r1["uncounted"] == "unattributed" and r1["state"] != "applicable", json.dumps(review)[:500])


def published_scenarios(workspace, invoke, check, fetch):
    """History survives project progress: publications, superseded criteria and later proposals."""
    root, base, remote = combined_root(workspace, invoke, check)

    def get(path, expect=200):
        status, payload = fetch(root, path)
        check(f"GET {path.split('?')[0]}: HTTP {expect}", status == expect, json.dumps(payload)[:400])
        return payload["data"] if expect == 200 else payload["error"]

    first = get("/api/v1/releases/engine/v1.0.0")
    second = get("/api/v1/releases/engine/v1.1.0")
    cli_release = cli(invoke, root, "inspect", "--release", "v1.0.0", "--component", "engine")["data"]
    check("V-020 published release resolves from its record without evaluating the gate", first["status"] == "published" and first["gate"] is None)
    check("V-020 publication matches the CLI record", first["publication"]["commit"] == cli_release["publication"]["commit"]
          and first["publication"]["preparation"] == cli_release["publication"]["evidence"]["preparation"] and first["publication"]["partial"] is False)
    check("V-021 each release keeps its own contract after the project advanced",
          first["contracts"][0]["revision"] == cli_release["publication"]["contracts"][CAP]
          and second["contracts"][0]["revision"] != first["contracts"][0]["revision"]
          and first["contracts"][0]["requirements"][0]["acceptance_ids"] == ["AC-001"]
          and second["contracts"][0]["requirements"][0]["acceptance_ids"] == ["AC-003"])
    old = first["contracts"][0]
    req = get(f"/api/v1/requirements/REQ-001?cap={CAP}&revision={old['revision']}&component=engine&release=v1.0.0")
    check("V-021 historical coverage is read from the recorded run", req["coverage"]["engine"]["criteria"]["AC-001"]["state"] == "covered"
          and req["coverage"]["engine"]["published"] is True and req["coverage"]["engine"]["candidate"] == "recorded")
    members = {m["change_id"]: m for m in second["members"]}
    check("V-022 combined release lists both later proposals", set(members) == {"CHG-002", "CHG-003"} and second["counts"]["integrated"] == 2)
    superseded = get(f"/api/v1/changes/CHG-002?revision={members['CHG-002']['intent_revision']}")
    base_revision = superseded["requirements"][0]["base_revisions"][0]
    check("V-022 superseded criterion stays consultable from its change context", base_revision == old["revision"]
          and get(f"/api/v1/requirements/REQ-001?cap={CAP}&revision={base_revision}&component=engine&change=CHG-002&intent={superseded['revision']}")["acceptance"][0]["id"] == "AC-001")
    proposal = get(f"/api/v1/requirements/REQ-001?cap={CAP}&revision={superseded['requirements'][0]['proposed_revision']}&component=engine&change=CHG-002&intent={superseded['revision']}")
    check("V-022 later proposal is its own revision", proposal["source"] in {"integrated", "proposal"} and proposal["revision"] != old["revision"]
          and proposal["context"]["change"] == "CHG-002")
    final_ac = second["contracts"][0]["requirements"][0]["acceptance_ids"]
    final = get(f"/api/v1/requirements/REQ-001?cap={CAP}&revision={second['contracts'][0]['revision']}&component=engine&release=v1.1.0")
    check("V-023 final contract criterion is the one the gate evaluates", list(final["coverage"]["engine"]["criteria"]) == final_ac)
    fix = get("/api/v1/changes/CHG-006")
    check("V-024 fixes show base contracts and declared scope", fix["kind"] == "fix" and fix["preserved"] and fix["fixes"][0]["acceptance_ids"] == ["AC-001"]
          and fix["baseline_release"]["version"] == "v1.0.0")
    fix_release = get("/api/v1/releases/engine/v1.0.6")
    check("V-024 correction release reports its own state", fix_release["kind"] == "bugfix" and fix_release["base_tag"] == "v1.0.0")
    return root


def combined_root(workspace, invoke, check):
    combined_and_fix_scenarios(workspace, invoke, check)
    return workspace / "c3-publication" / "code with spaces", None, None


def partial_provenance_scenarios(workspace, invoke, check, fetch):
    """A valid publication that predates preparations/runs reports which history it still has."""
    try:
        from .c1_scenarios import foundation, init_trunk, profile, seed_current, seed_publication, snapshot
    except ImportError:
        from c1_scenarios import foundation, init_trunk, profile, seed_current, seed_publication, snapshot
    root = workspace / "partial"
    init_trunk(root)
    config = workspace / "partial-profile.toml"
    profile(config)
    result = invoke(["--json", "init", str(root), "--profile", str(config)])
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    foundation(root)
    snap = snapshot()
    seed_current(root, snap)
    seed_publication(root, "v1.0.0", snap)
    status, payload = fetch(root, "/api/v1/releases/engine/v1.0.0")
    publication = (payload.get("data") or {}).get("publication") or {}
    check("V-025 partial provenance is a valid release that states what is missing",
          status == 200 and publication.get("partial") is True and publication["provenance"]["run"] is False and publication.get("note"), json.dumps(payload)[:400])
    status, payload = fetch(root, f"/api/v1/requirements/REQ-001?cap={CAP}&revision={snap['revision']}&component=engine&release=v1.0.0")
    criteria = payload["data"]["coverage"]["engine"]
    check("V-025 criteria without a preserved run are not evaluated", status == 200 and criteria["stop"]["code"] == "PROVENANCE_PARTIAL"
          and criteria["criteria"]["AC-001"]["state"] == "not-evaluated", json.dumps(criteria)[:400])
    return root
