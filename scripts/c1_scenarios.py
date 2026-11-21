"""Consumer-side C1 scenarios shared by unittest and the installed-wheel harness.

No imports from the Roclec implementation: all public operations use the provided
CLI callback. Historical contracts/publications are explicitly synthetic seeds,
not results of an integration or publication that C1 cannot perform.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_hash(value):
    return hashlib.sha256(value).hexdigest()


def put_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def init_trunk(root):
    subprocess.run(["git", "init", "-qb", "main", str(root)], check=True, capture_output=True)


def profile(path, names=("engine", "viewer"), repo="."):
    lines = ['schema = 3', 'name = "Synthetic consumer"', 'trunk_ref = "refs/heads/main"']
    for name in names:
        lines.extend([f'[components.{name}]', f'repo = {json.dumps(repo)}', 'user_facing = false',
                      'inputs = ["src/**", "tests/**"]', 'generated = ["build/**"]', 'target_ref = "refs/remotes/fixture/main"',
                      'verification = [{id="unit", argv=["python3", "-m", "unittest"], cwd=".", timeout_seconds=30}]'])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def snapshot(components=("engine", "viewer"), *, ac="AC-001", behavior="single line", req="REQ-001"):
    contents = {f"requirements/{req}.md": f"Display the result in {behavior}.\n",
                f"acceptance/{ac}.md": f"Given PASS and Saved, when opened, then the result uses {behavior}.\n"}
    descriptor = {"model_schema": 2, "capability_id": "CAP-001", "requirements": [
        {"id": req, "statement": f"requirements/{req}.md", "components": sorted(components), "acceptance_ids": [ac]}],
        "acceptance": [{"id": ac, "scenario": f"acceptance/{ac}.md", "components": sorted(components)}],
        "references": [], "files": {p: file_hash(b.encode()) for p, b in contents.items()}}
    return {"descriptor": descriptor, "revision": digest(descriptor), "content": contents}


def write_snapshot(folder, snap):
    put_json(folder / "contract.json", snap["descriptor"])
    for relative, body in snap["content"].items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def bundle(folder, *, change_id="CHG-001", target=None, base=None, components=("engine", "viewer"), kind="evolution"):
    folder.mkdir(parents=True, exist_ok=True)
    body = "Synthetic proposal: present the agreed result; preserve authorization.\n"
    scopes = sorted(components)
    semantic = {"intention": "proposal.md", "files": {"proposal.md": file_hash(body.encode())},
                "components": scopes, "bases": [{"capability_id": "CAP-001", "component": c,
                                                  "revision": base["revision"] if base else None} for c in scopes],
                "deltas": [], "proposed": [], "dependencies": [], "references": []}
    if kind == "evolution":
        target = target or snapshot(scopes)
        semantic["proposed"] = [{"capability_id": "CAP-001", "components": scopes, "revision": target["revision"]}]
        if base:
            old = base["descriptor"]["requirements"][0]["acceptance_ids"]
            new = target["descriptor"]["requirements"][0]["acceptance_ids"]
            semantic["deltas"] = [{"op": "revise", "capability_id": "CAP-001", "requirement_id": "REQ-001",
                                   "retire_acceptance_ids": sorted(set(old) - set(new)), "add_acceptance_ids": sorted(set(new) - set(old))}]
        else:
            semantic["deltas"] = [{"op": "add", "capability_id": "CAP-001", "requirement_id": "REQ-001"}]
        write_snapshot(folder / "proposed" / "CAP-001" / target["revision"], target)
    source_text = "Synthetic request: present the agreed result.\n"
    source_path = "origins/request.md"
    applicable = target if kind == "evolution" else base
    acceptance_ids = sorted({item["id"] for item in applicable["descriptor"]["acceptance"]
                             if set(item["components"]) & set(scopes)}) if applicable else []
    semantic["files"][source_path] = file_hash(source_text.encode())
    semantic["origins"] = [{"kind": "request", "id": f"request-{change_id}", "actor": "fixture user",
                            "locator": "synthetic fixture", "captured": source_path, "criteria": ["criterion-1"]}]
    semantic["coverage"] = {"criteria": [{"origin": f"request-{change_id}", "criterion": "criterion-1",
                                           "status": "covered", "acceptance_ids": acceptance_ids}], "derived": []}
    if not acceptance_ids:
        semantic["origins"][0]["criteria"] = []
        semantic["coverage"]["criteria"] = []
    (folder / "origins").mkdir(exist_ok=True)
    (folder / source_path).write_text(source_text, encoding="utf-8")
    record = {"model_schema": 2, "id": change_id, "kind": kind, "semantic": semantic}
    record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
    put_json(folder / "change.json", record)
    (folder / "proposal.md").write_text(body, encoding="utf-8")
    return record


def foundation(root, names=("engine", "viewer")):
    relative = "docs/reference.md"
    path = root / relative
    path.parent.mkdir(exist_ok=True)
    body = "# Synthetic foundation\n\nContext, principles, architecture, stack, engineering and verification are fixture data.\n"
    path.write_text(body, encoding="utf-8")
    roles = ["architecture", "context", "engineering", "principles", "stack", "verification"]
    seed_foundation(root, relative, names, roles)


def seed_foundation(root, relative, names, roles):
    refs = []
    source = file_hash((root / relative).read_bytes())
    for role in sorted(roles):
        decision = {"model_schema": 2, "entity": role, "previous": None, "kind": "foundation",
                    "status": "agreed", "actor": "synthetic fixture", "reason": "Synthetic test setup",
                    "sources": {role: source}}
        decision["id"] = digest(decision)
        put_json(root / f".roclec/decisions/{decision['id']}.json", decision)
        refs.append({"id": role, "path": relative, "components": sorted(names), "role": role, "decision_id": decision["id"]})
    put_json(root / ".roclec/references.json", {"model_schema": 2, "references": refs})


def seed_current(root, snap, names=("engine", "viewer")):
    """Explicit C2-result fixture used solely to test C1 reads/history/deltas."""
    write_snapshot(root / ".roclec/contracts/CAP-001" / snap["revision"], snap)
    path = root / ".roclec/current.json"
    current = json.loads(path.read_text())
    for name in names:
        current["components"][name]["CAP-001"] = snap["revision"]
    put_json(path, current)
    registry_path = root / ".roclec/identities.json"
    registry = json.loads(registry_path.read_text())
    identities = {"CAP-001": {"kind": "CAP", "owner": "CAP-001", "introduced_by": "CHG-900"}}
    for req in snap["descriptor"]["requirements"]:
        identities[req["id"]] = {"kind": "REQ", "owner": "CAP-001", "introduced_by": "CHG-900"}
        for ac in req["acceptance_ids"]:
            identities[ac] = {"kind": "AC", "owner": req["id"], "introduced_by": "CHG-900"}
    for key, value in identities.items():
        registry["identities"].setdefault(key, value)
    put_json(registry_path, registry)


def seed_publication(root, version, snap, *, component="engine", kind="release", base_tag=None):
    """Synthetic publication + real local Git tag, never a remote publication."""
    directory = root / ".roclec/releases" / component / version
    release_path = directory / "release.json"
    if release_path.exists():
        release = json.loads(release_path.read_text())
    else:
        release = {"model_schema": 2, "component": component, "version": version,
                   "kind": kind, "changes": [], "base_tag": base_tag}
        put_json(release_path, release)
    for command in (["git", "init", "-q"], ["git", "add", "."],
                    ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "synthetic base"]):
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    subprocess.run(["git", "tag", version, commit], cwd=root, check=True, capture_output=True)
    publication = {"model_schema": 2, "component": component, "version": version, "release_digest": digest(release),
                   "contracts": {"CAP-001": snap["revision"]}, "commit": commit, "tag": version,
                   "remote": "synthetic-fixture-only", "evidence": {"note": "Seeded reader fixture; C3 publication not executed"}}
    put_json(directory / "publication.json", publication)
    return publication


def tree(root):
    return {p.relative_to(root).as_posix(): (file_hash(p.read_bytes()), p.stat().st_mode & 0o777)
            for p in root.rglob("*") if p.is_file() and not p.is_symlink()
            and ".git" not in p.relative_to(root).parts and not p.relative_to(root).as_posix().startswith(".roclec/runtime/")}


def scenarios(workspace, invoke, check):
    """invoke(argv) -> CompletedProcess; check(name, condition, detail) records or fails."""
    root = workspace / "consumer with spaces"
    root.mkdir()
    init_trunk(root)
    (root / "AGENTS.md").write_text("# Existing consumer rules\n")
    (root / ".roclec/templates").mkdir(parents=True)
    (root / ".roclec/templates/custom.md").write_text("Project-owned template\n")
    config = workspace / "profile.toml"
    profile(config)

    def call(name, *args, expect=0, issue=None, initial=False):
        before = tree(root)
        argv = ["--json", *args] if initial else ["--project", str(root), "--json", *args]
        result = invoke(argv)
        try:
            data = json.loads(result.stdout)
        except (ValueError, TypeError) as exc:
            raise AssertionError(f"{name}: CLI output is not one JSON object: {result.stdout} {result.stderr}") from exc
        check(name, result.returncode == expect and data["ok"] == (expect == 0), result.stdout + result.stderr)
        check(name + ": envelope", set(data) == {"model_schema", "ok", "command", "data", "issues", "next_action"}, result.stdout)
        if issue:
            check(name + ": issue", any(i["code"] == issue for i in data["issues"]), result.stdout)
        if expect != 0:
            check(name + ": rejection preserves bytes and modes", before == tree(root), result.stdout)
        return data

    call("I-001 initialize native profile", "init", str(root), "--profile", str(config), initial=True)
    check("consumer files preserved", (root / "AGENTS.md").read_text() == "# Existing consumer rules\n"
          and (root / ".roclec/templates/custom.md").read_text() == "Project-owned template\n", "")
    check("no phantom contracts or old skills", not (root / ".roclec/contracts").exists() and not (root / ".agents").exists(), "")
    call("C1 empty project check", "check")
    call("I-001 refuse repeat init", "init", str(root), "--profile", str(config), initial=True, expect=1, issue="UNMANAGED_FILE")
    old_config = (root / ".roclec/project.toml").read_text()
    for old_schema in (1, 2):
        (root / ".roclec/project.toml").write_text(old_config.replace("schema = 3", f"schema = {old_schema}"))
        call(f"I-002 reject profile {old_schema} without migration", "check", expect=2, issue="UNSUPPORTED_SCHEMA")
    (root / ".roclec/project.toml").write_text(old_config)

    first = snapshot()
    draft = bundle(workspace / "draft-one", target=first)
    bundle_dir = workspace / "draft-one"
    manifest = bundle_dir / "change.json"
    unsealed = json.loads(manifest.read_bytes())
    unsealed.pop("proposal_digest")
    unsealed["semantic"].pop("files")
    entry = unsealed["semantic"]["proposed"][0]
    snapshot_parent = bundle_dir / "proposed/CAP-001"
    (snapshot_parent / entry.pop("revision")).rename(snapshot_parent / "draft")
    descriptor_path = snapshot_parent / "draft/contract.json"
    descriptor = json.loads(descriptor_path.read_bytes())
    descriptor.pop("files")
    put_json(descriptor_path, descriptor)
    put_json(manifest, unsealed)
    before = tree(root)
    original = manifest.read_bytes()
    call("F1 seal preview", "change", "seal", str(bundle_dir), "--check")
    check("F1 seal preview preserves bundle", manifest.read_bytes() == original, "")
    call("F1 seal generates proposal and snapshot hashes", "change", "seal", str(bundle_dir))
    sealed = manifest.read_bytes()
    check("FO seal includes captured source", "origins/request.md" in json.loads(sealed)["semantic"]["files"], "")
    repeated = call("F1 seal repeats", "change", "seal", str(bundle_dir))["data"]
    check("F1 seal is idempotent and leaves project intact", not repeated["changed"] and manifest.read_bytes() == sealed and tree(root) == before, "")
    saved_index = (root / ".roclec/current.json").read_bytes()
    call("I-001 create first capability on absent base", "change", "new", "--file", str(workspace / "draft-one/change.json"))
    check("I-003 draft never advances current", (root / ".roclec/current.json").read_bytes() == saved_index, "")
    call("I-004 reject duplicate change ID", "change", "new", "--file", str(workspace / "draft-one/change.json"), expect=1, issue="ID_COLLISION")
    call("I-009 start requires approval", "change", "start", "CHG-001", "--actor", "Fixture maintainer", "--component", "engine", expect=1, issue="APPROVAL_STALE")
    call("I-007 reject mismatched approval digest", "change", "approve", "CHG-001", "--digest", "0" * 64,
         "--actor", "fixture user", "--reason", "synthetic", expect=1, issue="APPROVAL_STALE")
    call("approve exact intention", "change", "approve", "CHG-001", "--digest", draft["proposal_digest"],
         "--actor", "fixture user", "--reason", "synthetic")
    call("F1 seal rejects approved snapshot", "change", "seal", str(bundle_dir), expect=3, issue="OPERATION_CONFLICT")
    call("I-009 foundation not inferred", "change", "start", "CHG-001", "--actor", "Fixture maintainer", "--component", "engine", expect=1, issue="FOUNDATION_INCOMPLETE")
    source = root / "docs/reference.md"
    source.parent.mkdir(exist_ok=True)
    original_source = b"# Synthetic foundation\n"
    source.write_bytes(original_source)
    for role in ("architecture", "context", "engineering", "principles", "stack", "verification"):
        call("F1 add foundation source " + role, "reference", "add", role, "--path", "docs/reference.md",
             "--component", "engine", "--component", "viewer", "--role", role)
        call("F1 agree foundation source " + role, "foundation", "agree", "--ref", role,
             "--actor", "Fixture maintainer", "--reason", "Reviewed synthetic source")
    call("agreed foundation checks", "foundation", "check", "--component", "engine", "--change", "CHG-001")
    source.write_bytes(original_source + b"Changed bytes\n")
    call("F1 edited source invalidates agreement", "foundation", "check", "--component", "engine",
         expect=1, issue="FOUNDATION_INCOMPLETE")
    source.write_bytes(original_source)
    call("I-009 release not inferred", "change", "start", "CHG-001", "--actor", "Fixture maintainer", "--component", "engine", expect=1, issue="RELEASE_UNASSIGNED")
    call("I-023 normal patch forbidden", "release", "plan", "engine", "v0.1.7", "--change", "CHG-001", expect=1, issue="VERSION_INVALID")
    call("plan engine independently", "release", "plan", "engine", "v0.1.0", "--change", "CHG-001")
    call("I-010 ambiguous start rejected", "change", "start", "CHG-001", "--actor", "Fixture maintainer", expect=2)
    call("start one component", "change", "start", "CHG-001", "--actor", "Fixture maintainer", "--component", "engine")
    call("other component remains unassigned", "change", "start", "CHG-001", "--actor", "Fixture maintainer", "--component", "viewer", expect=1, issue="RELEASE_UNASSIGNED")
    inspected = call("inspect per-component progress", "inspect", "--change", "CHG-001")["data"]
    check("progress is a vector", inspected["components"] == {"engine": "in-progress", "viewer": "not-started"}, "")
    (root / ".roclec/changes/CHG-001/notes.md").write_text("Administrative note only\n")
    inspected = call("I-008 administrative notes retain approval", "inspect", "--change", "CHG-001")["data"]
    check("administrative note is not semantic", inspected["approval_current"], "")

    change_file = root / ".roclec/changes/CHG-001/change.json"
    changed = json.loads(change_file.read_text())
    proposal_path = change_file.parent / "proposal.md"
    proposal_path.write_text(proposal_path.read_text() + "Add a material presentation constraint.\n")
    changed["semantic"]["files"]["proposal.md"] = file_hash(proposal_path.read_bytes())
    changed["proposal_digest"] = digest({k: changed[k] for k in ("id", "kind", "semantic")})
    put_json(change_file, changed)
    inspected = call("I-007 changed intention returns to draft", "inspect", "--change", "CHG-001")["data"]
    check("old approval remains historical", inspected["status"] == "draft" and not inspected["approval_current"]
          and inspected["approval"]["proposal_digest"] == draft["proposal_digest"], "")
    call("stale intention cannot start", "change", "start", "CHG-001", "--actor", "Fixture maintainer", "--component", "engine", expect=1, issue="APPROVAL_STALE")

    seed_current(root, first)
    second = snapshot(ac="AC-002", behavior="two labeled fields")
    evolution = bundle(workspace / "draft-two", change_id="CHG-002", target=second, base=first)
    call("evolve stable requirement with new AC", "change", "new", "--file", str(workspace / "draft-two/change.json"))
    live = call("I-003 pending delta preserves original AC", "inspect", "--capability", "CAP-001")["data"]
    check("DEF-001 original obligation retained", all(v["acceptance"][0]["id"] == "AC-001" for v in live["components"].values()), "")
    call("approve evolution", "change", "approve", "CHG-002", "--digest", evolution["proposal_digest"], "--actor", "fixture user", "--reason", "synthetic")
    bad_folder = workspace / "invalid-bundle"
    bad_target = snapshot(ac="AC-010", behavior="two separate values")
    bad = bundle(bad_folder, change_id="CHG-010", base=first, target=bad_target)
    proposal = bad_folder / "proposal.md"
    original_proposal = proposal.read_bytes()
    proposal.write_bytes(original_proposal + b"Unhashed edit\n")
    call("I-006 content mismatch rejected", "change", "new", "--file", str(bad_folder / "change.json"), expect=1, issue="HASH_MISMATCH")
    proposal.write_bytes(original_proposal)
    original_manifest = (bad_folder / "change.json").read_text()
    (bad_folder / "change.json").write_text(original_manifest.replace('"model_schema": 2', '"model_schema": 2, "model_schema": 2', 1))
    call("I-002 duplicate JSON key rejected", "change", "new", "--file", str(bad_folder / "change.json"), expect=2, issue="INVALID_INPUT")
    (bad_folder / "change.json").write_text(original_manifest)
    outside = workspace / "outside-proposal.md"
    outside.write_bytes(original_proposal)
    proposal.unlink()
    proposal.symlink_to(outside)
    call("I-002 symlink source rejected", "change", "new", "--file", str(bad_folder / "change.json"), expect=2, issue="INVALID_PATH")
    proposal.unlink()
    proposal.write_bytes(original_proposal)
    bad["semantic"]["files"]["../outside-proposal.md"] = file_hash(original_proposal)
    bad["proposal_digest"] = digest({k: bad[k] for k in ("id", "kind", "semantic")})
    put_json(bad_folder / "change.json", bad)
    call("I-002 parent traversal rejected", "change", "new", "--file", str(bad_folder / "change.json"), expect=2, issue="INVALID_PATH")
    foreign = bundle(workspace / "foreign-ac", change_id="CHG-011", base=first, target=bad_target)
    foreign["semantic"]["deltas"][0]["retire_acceptance_ids"] = ["AC-999"]
    foreign["proposal_digest"] = digest({k: foreign[k] for k in ("id", "kind", "semantic")})
    put_json(workspace / "foreign-ac/change.json", foreign)
    call("I-004 foreign criterion rejected", "change", "new", "--file", str(workspace / "foreign-ac/change.json"), expect=1, issue="INVALID_REFERENCE")
    seed_publication(root, "v0.1.0", first)
    call("plan minor increment", "release", "plan", "engine", "v0.3.0", "--change", "CHG-002")
    call("I-024 duplicate assignment", "release", "plan", "engine", "v0.4.0", "--change", "CHG-002", expect=1, issue="RELEASE_DUPLICATE")
    call("I-023 invalid major subordinate reset", "release", "plan", "engine", "v1.2.0", "--clear", expect=1, issue="VERSION_INVALID")
    call("I-023 valid major reset", "release", "plan", "engine", "v2.0.0", "--clear")
    call("I-023 historical new version rejected", "release", "plan", "engine", "v0.8", "--clear", expect=1, issue="VERSION_INVALID")
    fix = bundle(workspace / "fix", change_id="CHG-003", base=first, components=("engine",), kind="fix")
    call("capture preserving fix", "change", "new", "--file", str(workspace / "fix/change.json"))
    call("approve preserving fix", "change", "approve", "CHG-003", "--digest", fix["proposal_digest"], "--actor", "fixture user", "--reason", "synthetic")
    call("I-023 valid bugfix may skip patch numbers", "release", "plan", "engine", "v0.1.3", "--kind", "bugfix", "--base-tag", "v0.1.0", "--change", "CHG-003")
    base_commit = subprocess.check_output(["git", "rev-parse", "refs/tags/v0.1.0^{commit}"], cwd=root, text=True).strip()
    subprocess.run(["git", "tag", "-d", "v0.1.0"], cwd=root, check=True, capture_output=True)
    call("I-023 recorded base still needs real Git tag", "release", "plan", "engine", "v0.1.3", "--kind", "bugfix", "--base-tag", "v0.1.0", "--change", "CHG-003", expect=1, issue="INVALID_REFERENCE")
    subprocess.run(["git", "tag", "v0.1.0", base_commit], cwd=root, check=True, capture_output=True)
    seed_publication(root, "v0.1.5", first, kind="bugfix", base_tag="v0.1.0")
    call("I-023 patch must exceed latest published patch", "release", "plan", "engine", "v0.1.3", "--kind", "bugfix", "--base-tag", "v0.1.0", "--change", "CHG-003", expect=1, issue="VERSION_INVALID")
    call("I-023 correction requires nonzero patch", "release", "plan", "engine", "v0.2.0", "--kind", "hotfix", "--base-tag", "v0.1.0", "--clear", expect=1, issue="VERSION_INVALID")
    call("I-023 correction rejects different line", "release", "plan", "engine", "v0.2.1", "--kind", "hotfix", "--base-tag", "v0.1.0", "--clear", expect=1, issue="VERSION_INVALID")
    call("I-023 correction requires a real base record", "release", "plan", "engine", "v0.1.8", "--kind", "hotfix", "--base-tag", "v0.1.2", "--clear", expect=1, issue="INVALID_REFERENCE")
    call("I-029 correction rejects evolution", "release", "plan", "viewer", "v0.1.1", "--kind", "bugfix", "--base-tag", "v0.1.0", "--change", "CHG-002", expect=1, issue="VERSION_INVALID")

    for number in (1, 2):
        fut = {"model_schema": 2, "id": f"FUT-{number:03}", "source": {"location": "docs/reference.md", "locator": "Synthetic context"},
               "finding": "Potential improvement", "impact": "Needs evaluation", "questions": ["Does this belong in scope?"]}
        path = workspace / f"fut-{number}.json"
        put_json(path, fut)
        call("capture discovery " + str(number), "fut", "capture", "--file", str(path))
    call("I-021 promotion needs existing target", "fut", "decide", "FUT-001", "--outcome", "promoted", "--target", "CHG-999", "--actor", "fixture user", "--reason", "synthetic", expect=1, issue="INVALID_REFERENCE")
    call("I-021 no duplicate self-reference", "fut", "decide", "FUT-001", "--outcome", "duplicate", "--target", "FUT-001", "--actor", "fixture user", "--reason", "synthetic", expect=1, issue="INVALID_REFERENCE")
    call("I-022 discard retains discovery", "fut", "decide", "FUT-001", "--outcome", "discarded", "--actor", "fixture user", "--reason", "synthetic")
    call("I-022 explicit reevaluation", "fut", "decide", "FUT-001", "--outcome", "evaluating", "--actor", "fixture user", "--reason", "new information")
    call("promote without approving destination", "fut", "decide", "FUT-001", "--outcome", "promoted", "--target", "CHG-001", "--actor", "fixture user", "--reason", "synthetic")
    destination = call("promotion does not change destination approval", "inspect", "--change", "CHG-001")["data"]
    check("unapproved destination remains draft", destination["status"] == "draft" and not destination["approval_current"], "")
    fut = call("discovery history remains", "inspect", "--fut", "FUT-001")["data"]
    check("all FUT decisions retained", len(fut["decisions"]) == 3 and fut["status"] == "promoted", "")
    call("record valid duplicate", "fut", "decide", "FUT-002", "--outcome", "duplicate", "--target", "FUT-001", "--actor", "fixture user", "--reason", "same discovery")
    call("reevaluate promoted discovery explicitly", "fut", "decide", "FUT-001", "--outcome", "evaluating", "--actor", "fixture user", "--reason", "new information")
    call("reject a two-discovery duplicate cycle", "fut", "decide", "FUT-001", "--outcome", "duplicate", "--target", "FUT-002", "--actor", "fixture user", "--reason", "synthetic", expect=1, issue="INVALID_REFERENCE")

    # FO uses a preservation change so it can exercise approval independently of
    # the normative delta scenarios above.
    origin_folder = workspace / "origin-fixture"
    origin_record = bundle(origin_folder, change_id="CHG-100", base=first, components=("viewer",), kind="fix")
    origin_file = origin_folder / "change.json"
    call("FO import origin-bearing change", "change", "new", "--file", str(origin_file))
    stored_folder = root / ".roclec/changes/CHG-100"
    stored_manifest = stored_folder / "change.json"

    def edit_origin_record(record):
        record["proposal_digest"] = digest({key: record[key] for key in ("id", "kind", "semantic")})
        put_json(stored_manifest, record)
        return record["proposal_digest"]

    def approve_origin(name, record, *, expect=0, issue=None):
        revision = edit_origin_record(record)
        return call(name, "change", "approve", "CHG-100", "--digest", revision,
                    "--actor", "fixture user", "--reason", "synthetic source review", expect=expect, issue=issue)

    legacy = json.loads(json.dumps(origin_record))
    del legacy["semantic"]["origins"]
    del legacy["semantic"]["coverage"]
    approve_origin("FO origin required for approval", legacy, expect=1, issue="ORIGIN_REQUIRED")
    missing_file = json.loads(json.dumps(origin_record))
    del missing_file["semantic"]["files"]["origins/request.md"]
    approve_origin("FO captured source must be in manifest", missing_file, expect=1, issue="INVALID_ORIGIN")
    gap = json.loads(json.dumps(origin_record))
    gap["semantic"]["coverage"]["criteria"][0] = {"origin": "request-CHG-100", "criterion": "criterion-1",
                                                        "status": "gap", "question": "What should happen?"}
    edit_origin_record(gap)
    result = call("FO open gap blocks approval", "check", "--change", "CHG-100", "--gate", "approve", expect=1, issue="ORIGIN_GAP")
    check("FO gap identifies criterion", "criterion-1" in json.dumps(result["issues"]), str(result))
    approve_origin("FO open gap blocks actual approval", gap, expect=1, issue="ORIGIN_GAP")
    no_coverage = json.loads(json.dumps(origin_record))
    no_coverage["semantic"]["coverage"]["criteria"] = []
    approve_origin("FO every source criterion needs coverage", no_coverage, expect=1, issue="INVALID_COVERAGE")
    excluded = json.loads(json.dumps(origin_record))
    excluded["semantic"]["coverage"]["criteria"][0] = {"origin": "request-CHG-100", "criterion": "criterion-1",
                                                             "status": "excluded", "reason": ""}
    approve_origin("FO exclusion needs a reason", excluded, expect=1, issue="INVALID_COVERAGE")
    unknown_fut = json.loads(json.dumps(excluded))
    unknown_fut["semantic"]["coverage"]["criteria"][0] = {"origin": "request-CHG-100", "criterion": "criterion-1",
                                                                "status": "deferred", "fut": "FUT-999"}
    approve_origin("FO deferral needs an existing FUT", unknown_fut, expect=1, issue="INVALID_REFERENCE")
    missing_capture = stored_folder / "origins/request.md"
    capture_bytes = missing_capture.read_bytes()
    missing_capture.unlink()
    approve_origin("FO missing captured file is rejected", origin_record, expect=1, issue="INVALID_REFERENCE")
    missing_capture.write_bytes(capture_bytes)
    for number in (3, 4, 5, 6, 7):
        discovery = {"model_schema": 2, "id": f"FUT-{number:03}",
                     "source": {"location": "docs/reference.md", "locator": "Synthetic context"},
                     "finding": "Potential improvement", "impact": "Needs evaluation", "questions": []}
        discovery_path = workspace / f"fo-fut-{number}.json"
        put_json(discovery_path, discovery)
        call("FO capture discovery " + str(number), "fut", "capture", "--file", str(discovery_path))
    fut_origin = json.loads(json.dumps(origin_record))
    fut_origin["semantic"]["origins"][0] = {"kind": "fut", "id": "FUT-003", "locator": "synthetic finding",
                                               "captured": "origins/request.md", "criteria": ["criterion-1"]}
    fut_origin["semantic"]["coverage"]["criteria"][0]["origin"] = "FUT-003"
    approve_origin("FO unpromoted FUT cannot approve", fut_origin, expect=1, issue="INVALID_ORIGIN")
    # The FUT promotion resolves against the current imported draft.
    edit_origin_record(fut_origin)
    call("FO promote FUT to draft", "fut", "decide", "FUT-003", "--outcome", "promoted", "--target", "CHG-100",
         "--actor", "fixture user", "--reason", "Requested work")
    approve_origin("FO promoted FUT approves", fut_origin)
    duplicate_origin = json.loads(json.dumps(fut_origin))
    duplicate_origin["semantic"]["origins"][0]["id"] = "FUT-004"
    duplicate_origin["semantic"]["coverage"]["criteria"][0]["origin"] = "FUT-004"
    edit_origin_record(duplicate_origin)
    call("FO mark FUT duplicate of change", "fut", "decide", "FUT-004", "--outcome", "duplicate", "--target", "CHG-100",
         "--actor", "fixture user", "--reason", "Same work")
    approve_origin("FO duplicate FUT approves", duplicate_origin)
    chained_origin = json.loads(json.dumps(fut_origin))
    chained_origin["semantic"]["origins"][0]["id"] = "FUT-005"
    chained_origin["semantic"]["coverage"]["criteria"][0]["origin"] = "FUT-005"
    edit_origin_record(chained_origin)
    call("FO duplicate FUT can resolve through another FUT", "fut", "decide", "FUT-005", "--outcome", "duplicate", "--target", "FUT-003",
         "--actor", "fixture user", "--reason", "Same finding")
    approve_origin("FO FUT duplicate chain approves", chained_origin)
    excluded["semantic"]["coverage"]["criteria"][0]["reason"] = "Outside scope by user decision"
    approve_origin("FO excluded criterion on preservation change approves", excluded)
    deferred = json.loads(json.dumps(excluded))
    deferred["semantic"]["coverage"]["criteria"][0] = {"origin": "request-CHG-100", "criterion": "criterion-1",
                                                              "status": "deferred", "fut": "FUT-006"}
    approve_origin("FO deferred criterion names existing FUT", deferred)
    approve_origin("FO approve complete coverage", origin_record)
    approved_revision = origin_record["proposal_digest"]
    frozen = stored_folder / "revisions" / approved_revision / "origins/request.md"
    captured_before = frozen.read_bytes()
    captured = stored_folder / "origins/request.md"
    captured.write_bytes(captured.read_bytes() + b"A revised request.\n")
    changed_origin = json.loads(json.dumps(origin_record))
    changed_origin["semantic"]["files"]["origins/request.md"] = file_hash(captured.read_bytes())
    new_revision = edit_origin_record(changed_origin)
    inspected_origin = call("FO changed source requires a new approval", "inspect", "--change", "CHG-100")["data"]
    check("FO source snapshot stays frozen", new_revision != approved_revision and not inspected_origin["approval_current"]
          and frozen.read_bytes() == captured_before, str(inspected_origin))
    approve_origin("FO approve revised captured source", changed_origin)
    second_folder = workspace / "shared-origin-fixture"
    shared = bundle(second_folder, change_id="CHG-101", base=first, components=("viewer",), kind="fix")
    shared["semantic"]["origins"][0]["id"] = "request-CHG-100"
    shared["semantic"]["coverage"]["criteria"][0]["origin"] = "request-CHG-100"
    shared["semantic"]["origins"].append({"kind": "issue", "id": "issue-extra", "locator": "synthetic issue",
                                             "captured": "origins/request.md", "criteria": []})
    shared["proposal_digest"] = digest({key: shared[key] for key in ("id", "kind", "semantic")})
    put_json(second_folder / "change.json", shared)
    call("FO import change with two origins", "change", "new", "--file", str(second_folder / "change.json"))
    listed = call("FO inverse origin query", "list", "changes", "--origin", "request-CHG-100")["data"]["changes"]
    check("FO inverse query returns both changes", {item["id"] for item in listed} == {"CHG-100", "CHG-101"}, str(listed))
    displayed = call("FO inspect origins and coverage", "inspect", "--change", "CHG-101")["data"]
    check("FO inspection exposes both origins and coverage", len(displayed["origins"]) == 2
          and displayed["coverage"] == shared["semantic"]["coverage"], str(displayed))
    call("FO promote FUT to a different change", "fut", "decide", "FUT-007", "--outcome", "promoted", "--target", "CHG-101",
         "--actor", "fixture user", "--reason", "Different work")
    wrong_target = json.loads(json.dumps(changed_origin))
    wrong_target["semantic"]["origins"][0] = {"kind": "fut", "id": "FUT-007", "locator": "synthetic finding",
                                                  "captured": "origins/request.md", "criteria": ["criterion-1"]}
    wrong_target["semantic"]["coverage"]["criteria"][0]["origin"] = "FUT-007"
    approve_origin("FO FUT promoted to another change is rejected", wrong_target, expect=1, issue="INVALID_ORIGIN")
    edit_origin_record(changed_origin)

    # An evolution retains AC-001 and introduces AC-102. Coverage is required
    # for the new AC without reclassifying the existing obligation as derived.
    evolution_target = snapshot(("viewer",), ac="AC-102")
    evolution_target["content"]["acceptance/AC-001.md"] = first["content"]["acceptance/AC-001.md"]
    descriptor = evolution_target["descriptor"]
    descriptor["requirements"][0]["acceptance_ids"] = ["AC-001", "AC-102"]
    descriptor["acceptance"].insert(0, {"id": "AC-001", "scenario": "acceptance/AC-001.md", "components": ["viewer"]})
    descriptor["files"]["acceptance/AC-001.md"] = file_hash(evolution_target["content"]["acceptance/AC-001.md"].encode())
    evolution_target["revision"] = digest(descriptor)
    evolution_folder = workspace / "origin-evolution"
    evolution = bundle(evolution_folder, change_id="CHG-102", base=first, target=evolution_target, components=("viewer",))
    evolution["semantic"]["coverage"]["criteria"][0]["acceptance_ids"] = ["AC-102"]
    evolution["proposal_digest"] = digest({key: evolution[key] for key in ("id", "kind", "semantic")})
    put_json(evolution_folder / "change.json", evolution)
    call("FO import evolution covering only new AC", "change", "new", "--file", str(evolution_folder / "change.json"))
    evolution_manifest = root / ".roclec/changes/CHG-102/change.json"
    uncovered = json.loads(json.dumps(evolution))
    uncovered["semantic"]["coverage"]["criteria"][0] = {"origin": "request-CHG-102", "criterion": "criterion-1",
                                                            "status": "excluded", "reason": "Out of scope"}
    uncovered["proposal_digest"] = digest({key: uncovered[key] for key in ("id", "kind", "semantic")})
    put_json(evolution_manifest, uncovered)
    call("FO new AC needs coverage or a derived reason", "change", "approve", "CHG-102", "--digest", uncovered["proposal_digest"],
         "--actor", "fixture user", "--reason", "synthetic review", expect=1, issue="INVALID_COVERAGE")
    uncovered["semantic"]["coverage"]["derived"] = [{"id": "AC-102", "reason": "Gap identified during specification"}]
    uncovered["proposal_digest"] = digest({key: uncovered[key] for key in ("id", "kind", "semantic")})
    put_json(evolution_manifest, uncovered)
    call("FO new derived AC approves without mapping unchanged AC", "change", "approve", "CHG-102", "--digest", uncovered["proposal_digest"],
         "--actor", "fixture user", "--reason", "synthetic review")

    seed_current(root, second, names=("engine",))
    vector = call("I-011 read synthetic partial integration vector", "inspect", "--capability", "CAP-001")["data"]["components"]
    check("I-011 read scope only; C2 integration not executed", vector["engine"]["revision"] == second["revision"]
          and vector["viewer"]["revision"] == first["revision"], "Historical state was seeded explicitly")
    historical = call("I-005 historical release keeps previous revision", "inspect", "--capability", "CAP-001", "--component", "engine", "--at", "v0.1.0")["data"]
    check("old release resolves old AC", historical["components"]["engine"]["acceptance"][0]["id"] == "AC-001", "")
    call("missing generated view is reported", "views", expect=1, issue="VIEW_STALE")
    call("generate contract view", "views", "--write")
    call("generated contract view is current", "views")
    view = root / "specs/capabilities/CAP-001.md"
    view.write_text(view.read_text() + "Consumer edit\n")
    call("preserve hand-edited view", "views", "--write", expect=1, issue="UNMANAGED_FILE")
    call("C2 requires explicit base", "run", "verify", "CHG-002", "--component", "engine",
         "--role", "implementer", "--context", "synthetic implementer session", expect=2, issue="INVALID_INPUT")
    call("C3 preparation requires explicit release run and output", "release", "prepare", "engine", "v0.3.0", expect=2, issue="INVALID_INPUT")
    call("JSON usage error has no success envelope", "inspect", "--nonsense", expect=2, issue="INVALID_INPUT")
    return root
