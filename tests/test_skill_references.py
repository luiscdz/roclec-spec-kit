"""Knowledge skills as foundation references: fingerprints, flow assignment, approval pin and implement gate (TK.1, TK.2)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from roclec_spec_kit.config import load_profile
from roclec_spec_kit.flow import STAGES
from roclec_spec_kit.kernel import Kernel
from roclec_spec_kit.knowledge import manifest_digest, skill_files, source_fingerprint
from roclec_spec_kit.model import ModelError
from roclec_spec_kit.store import Store
from scripts.c1_scenarios import bundle, criteria, foundation, init_trunk, profile, put_json, tree
try:
    from test_kernel import invoke
except ModuleNotFoundError:  # run as tests.test_skill_references
    from tests.test_kernel import invoke

FLOW = ".roclec/flow.toml"
ACTOR = ("--actor", "Maintainer", "--reason", "Reviewed")
SKILL = "conventions"
LOCATION = f".agents/skills/{SKILL}"


def codes(payload):
    return [i["code"] for i in payload["issues"]]


class SkillReferenceTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)
        self.root = self.workspace / "project"
        self.config = self.workspace / "profile.toml"
        profile(self.config)
        init_trunk(self.root)
        result = invoke(["--json", "init", str(self.root), "--profile", str(self.config)])
        self.assertEqual(result.returncode, 0, result.stdout)
        foundation(self.root)

    def call(self, *args, expect=0, issue=None):
        before = tree(self.root)
        result = invoke(["--project", str(self.root), "--json", *args])
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        if issue:
            self.assertIn(issue, codes(payload), result.stdout)
        if expect in (1, 2, 3):
            self.assertEqual(tree(self.root), before, "Rejected operation mutated consumer")
        return payload

    def skill(self, name=SKILL, files=None):
        folder = self.root / ".agents/skills" / name
        for relative, body in (files or {"SKILL.md": f"---\nname: {name}\n---\n\n# Conventions\n",
                                         "examples/handler.md": "# Handler example\n"}).items():
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        return folder

    def register(self, name=SKILL, *extra, action="add", expect=0, issue=None):
        return self.call("reference", action, name, "--path", f".agents/skills/{name}", "--role", "skill",
                         "--component", "engine", *extra, expect=expect, issue=issue)

    def agree(self, name=SKILL, *extra, expect=0, issue=None):
        return self.call("foundation", "agree", "--ref", name, *ACTOR, *criteria(self.root, "foundation"), *extra,
                         expect=expect, issue=issue)

    def pin(self, name=SKILL):
        return manifest_digest(skill_files(self.root, f".agents/skills/{name}"))

    def assign(self, stage, names):
        path = self.root / FLOW
        text = path.read_text(encoding="utf-8")
        header = f"[stages.{stage}]\n"
        self.assertEqual(text.count(header), 1)
        path.write_text(text.replace(header, header + f"skills = {json.dumps(names)}\n"), encoding="utf-8")

    # TK.1 — fingerprint and registration

    def test_any_file_change_changes_the_fingerprint(self):
        folder = self.skill()
        ref = {"id": SKILL, "path": LOCATION, "role": "skill"}
        seen = {source_fingerprint(self.root, ref)}
        self.assertEqual(seen, {self.pin()})
        edits = [
            lambda: (folder / "SKILL.md").write_text("---\nname: conventions\n---\n\n# Edited\n"),
            lambda: (folder / "examples/handler.md").write_text("# Nested edit\n"),
            lambda: (folder / ".hidden").write_text("hidden\n"),
            lambda: (folder / ".hidden").write_text("hidden edit\n"),
            lambda: (folder / "examples/more.md").write_text("# Added\n"),
            lambda: (folder / "examples/more.md").rename(folder / "examples/renamed.md"),
            lambda: (folder / "examples/handler.md").unlink(),
        ]
        for edit in edits:
            edit()
            current = source_fingerprint(self.root, ref)
            self.assertNotIn(current, seen)
            seen.add(current)
        # Deterministic: same files, same fingerprint.
        self.assertEqual(source_fingerprint(self.root, ref), self.pin())
        self.assertIsNone(source_fingerprint(self.root, {"id": "absent", "path": ".agents/skills/absent", "role": "skill"}))

    def test_inspect_shows_stale_after_agreement_and_edit(self):
        folder = self.skill()
        self.register()
        self.assertEqual(self.call("inspect", "--reference", SKILL)["data"]["state"], "draft")
        decision = self.agree()["data"]["decision"]
        self.assertEqual(decision["sources"], {SKILL: self.pin()})
        inspected = self.call("inspect", "--reference", SKILL)["data"]
        self.assertEqual((inspected["state"], inspected["sha256"]), ("approved", self.pin()))
        (folder / "examples/nested").mkdir()
        (folder / "examples/nested/.rule").write_text("deep hidden rule\n")
        inspected = self.call("inspect", "--reference", SKILL)["data"]
        self.assertEqual((inspected["state"], inspected["sha256"]), ("stale", self.pin()))
        self.agree()
        self.assertEqual(self.call("inspect", "--reference", SKILL)["data"]["state"], "approved")

    def test_unsafe_or_misplaced_skills_are_rejected_without_writes(self):
        outside = self.root / "shared"
        outside.mkdir()
        (outside / "rules.md").write_text("# Shared\n")
        folder = self.skill()
        os.symlink(outside / "rules.md", folder / "linked.md")
        rejected = self.register(expect=2, issue="INVALID_PATH")
        self.assertEqual(rejected["issues"][0]["path"], f"{LOCATION}/linked.md")
        (folder / "linked.md").unlink()
        os.symlink(outside, folder / "examples/shared")
        rejected = self.register(expect=2, issue="INVALID_PATH")
        self.assertEqual(rejected["issues"][0]["path"], f"{LOCATION}/examples/shared")
        (folder / "examples/shared").unlink()
        os.symlink(folder, self.root / ".agents/skills/alias")
        self.register("alias", expect=2, issue="INVALID_PATH")
        # The canonical location only: .agents/skills/<id>, no other folder or trailing slash.
        for path in (".agents/skills/other", "docs", f"{LOCATION}/"):
            self.call("reference", "add", SKILL, "--path", path, "--role", "skill", "--component", "engine",
                      expect=2, issue="INVALID_PATH")
        self.skill("roclec-x")
        self.register("roclec-x", expect=2, issue="INVALID_INPUT")
        self.skill("speckit-x")
        self.register("speckit-x", expect=2, issue="INVALID_INPUT")
        empty = self.skill("empty", {"SKILL.md": "  \n", "notes.md": "# Notes\n"})
        self.register("empty", expect=1, issue="INVALID_REFERENCE")
        (empty / "SKILL.md").unlink()
        self.register("empty", expect=1, issue="INVALID_REFERENCE")
        (self.root / ".agents/skills/missing").mkdir()
        self.register("missing", expect=1, issue="INVALID_REFERENCE")
        (self.root / ".agents/skills/plain").write_text("# A file, not a skill directory\n")
        self.register("plain", expect=1, issue="INVALID_REFERENCE")
        self.call("reference", "add", SKILL, "--path", LOCATION, "--role", "skill", "--component", "engine",
                  "--supersedes", "ADR-001", expect=2, issue="INVALID_INPUT")
        self.register()
        registered = json.loads((self.root / ".roclec/references.json").read_text())["references"]
        self.assertIn({"id": SKILL, "path": LOCATION, "components": ["engine"], "role": "skill", "decision_id": None},
                      registered)

    def test_symlink_added_after_agreement_blocks_foundation_not_the_project(self):
        folder = self.skill()
        self.register()
        self.agree()
        os.symlink(self.root / "docs/reference.md", folder / "linked.md")
        self.call("check")  # The store token records the link without following it.
        blocked = self.call("foundation", "check", "--component", "engine", expect=1, issue="INVALID_PATH")
        self.assertIn(f"{LOCATION}/linked.md", [i["path"] for i in blocked["issues"]])
        self.call("inspect", "--reference", SKILL, expect=2, issue="INVALID_PATH")
        self.agree(expect=2, issue="INVALID_PATH")

    def test_store_token_changes_when_a_skill_file_changes(self):
        folder = self.skill()
        self.register()
        store = Store(self.root)
        self.assertIn(f"{LOCATION}/examples/handler.md", store.inputs())
        tokens = [store.token()]
        for edit in (lambda: (folder / "examples/handler.md").write_text("# Edited\n"),
                     lambda: (folder / ".hidden").write_text("x\n"),
                     lambda: os.symlink("SKILL.md", folder / "alias.md")):
            edit()
            tokens.append(store.token())
        self.assertEqual(len(set(tokens)), 4)
        self.assertTrue(store.inputs()[f"{LOCATION}/alias.md"].startswith("symlink:"))
        (folder / "alias.md").unlink()
        self.assertEqual(store.token(), tokens[2])  # Removing the link restores the earlier file set.
        # A write validated against an older token is refused.
        kernel = Kernel(load_profile(self.root))
        (folder / "SKILL.md").write_text("---\nname: conventions\n---\n\n# Concurrent edit\n")
        with self.assertRaises(ModelError) as raised:
            kernel.agree_foundation(SKILL, "Maintainer", "Reviewed",
                                    criteria=json.loads(Path(criteria(self.root, "foundation")[1]).read_text()))
        self.assertEqual(raised.exception.issue["code"], "BASE_CONFLICT")

    # TK.1 — rejection freezes the directory

    def test_rejected_skill_freezes_every_file_and_is_reagreed_with_addresses(self):
        folder = self.skill()
        (folder / ".hidden").write_text("hidden\n")
        self.register()
        pin = self.pin()
        corrections = self.workspace / "corrections.json"
        put_json(corrections, [{"id": "R-1", "description": "Cite the architecture reference"}])
        rejection = self.call("reject", "reference", SKILL, "--digest", pin, *ACTOR, "--consequence", "revise",
                              "--corrections", str(corrections), *criteria(self.root, "foundation", "rejected"))
        decision = rejection["data"]["decision"]
        self.assertEqual(decision["subject"], {"type": "reference", "entity": SKILL, "digest": pin})
        self.assertEqual(sorted(decision["files"]), ["content/.hidden", "content/SKILL.md", "content/examples/handler.md"])
        frozen = self.root / Rejections_root(decision)
        for relative in ("SKILL.md", ".hidden", "examples/handler.md"):
            self.assertEqual((frozen / "content" / relative).read_bytes(), (folder / relative).read_bytes())
        self.call("check")
        self.assertEqual(self.call("inspect", "--reference", SKILL)["data"]["state"], "rejected")
        # A wrong digest (e.g. SKILL.md alone) is not the subject.
        self.call("reject", "reference", SKILL, "--digest", "0" * 64, *ACTOR, "--corrections", str(corrections),
                  *criteria(self.root, "foundation", "rejected"), expect=1, issue="APPROVAL_STALE")
        self.agree(expect=1, issue="REJECTION_UNRESOLVED")
        (folder / "SKILL.md").write_text("---\nname: conventions\n---\n\n# Conventions\n\nSee `architecture`.\n")
        self.agree(expect=1, issue="CORRECTIONS_REQUIRED")
        addresses = self.workspace / "addresses.json"
        put_json(addresses, {"rejection": decision["id"], "corrections": [{"id": "R-1", "status": "addressed"}]})
        self.agree(SKILL, "--addresses", str(addresses))
        inspected = self.call("inspect", "--reference", SKILL)["data"]
        self.assertEqual(inspected["state"], "approved")
        self.assertFalse(inspected["rejections"][0]["open"])
        self.call("check")
        # A tampered frozen copy is detected.
        (frozen / "content/.hidden").write_text("tampered\n")
        self.call("check", expect=1, issue="HASH_MISMATCH")

    # TK.2 — flow assignment

    def test_flow_skills_must_name_registered_skill_references(self):
        self.assign("implement", ["unknown"])
        failed = self.call("check", expect=2, issue="FLOW_SKILL_UNREGISTERED")
        issue = failed["issues"][0]
        self.assertEqual(issue["entity"], "stages.implement.skills")
        self.assertIn("reference add unknown --path .agents/skills/unknown --role skill", issue["remediation"])
        self.agree("flow", expect=2, issue="FLOW_SKILL_UNREGISTERED")
        self.call("foundation", "check", "--component", "engine", expect=1, issue="FOUNDATION_INCOMPLETE")
        flow = (self.root / FLOW).read_text().replace('skills = ["unknown"]', 'skills = ["context"]')
        (self.root / FLOW).write_text(flow)
        failed = self.call("check", expect=2, issue="FLOW_SKILL_UNREGISTERED")
        self.assertEqual(failed["issues"][0]["actual"], "context")
        self.agree("flow", expect=2, issue="FLOW_SKILL_UNREGISTERED")
        self.skill()
        self.register()
        (self.root / FLOW).write_text(flow.replace('skills = ["context"]', f'skills = ["{SKILL}"]'))
        self.assertNotIn("FLOW_SKILL_UNREGISTERED", codes(self.call("check")))
        self.agree("flow")
        # The flow cites it: it must stay a skill.
        self.call("reference", "update", SKILL, "--path", LOCATION, "--role", "context", "--component", "engine",
                  expect=1, issue="INVALID_REFERENCE")
        self.register(SKILL, "--component", "viewer", action="update")

    def test_applicable_skills_by_component_and_stage(self):
        for name in ("alpha", "beta", "gamma"):
            self.skill(name)
        self.register("alpha")
        self.register("beta")
        self.call("reference", "add", "gamma", "--path", ".agents/skills/gamma", "--role", "skill",
                  "--component", "viewer")
        self.assign("implement", ["alpha"])
        self.assign("review", ["alpha"])
        kernel = Kernel(load_profile(self.root))
        ids = lambda rows: [r["id"] for r in rows]
        self.assertEqual(ids(kernel.applicable_skills("engine")), ["alpha", "beta"])
        self.assertEqual(ids(kernel.applicable_skills("engine", "implement")), ["alpha", "beta"])
        self.assertEqual(ids(kernel.applicable_skills("engine", "verify")), ["beta"])
        self.assertEqual(ids(kernel.applicable_skills("viewer", "verify")), ["gamma"])
        self.assertEqual(kernel.applicable_skills("engine")[0]["stages"], ["implement", "review"])
        self.assertEqual(kernel.applicable_skills("engine")[1]["stages"], list(STAGES))
        with self.assertRaises(ModelError):
            kernel.applicable_skills("engine", "deploy")

    # TK.2 — approval pin and implement gate

    def test_agree_approve_edit_blocks_implement_until_reagreed(self):
        folder = self.skill()
        self.register()
        self.agree()
        pin = self.pin()
        draft = self.workspace / "draft"
        record = bundle(draft)
        self.call("change", "new", "--file", str(draft / "change.json"))
        self.call("check", "--change", "CHG-001", "--gate", "approve")
        approval = self.call("change", "approve", "CHG-001", "--digest", record["proposal_digest"], *ACTOR,
                             *criteria(self.root, "approve"))["data"]["decision"]
        self.assertEqual(approval["skills"], [{"id": SKILL, "sha256": pin}])
        self.call("release", "plan", "engine", "v0.1.0", "--change", "CHG-001")
        gate = ("check", "--change", "CHG-001", "--component", "engine", "--gate", "implement")
        self.call(*gate)
        (folder / "examples/handler.md").write_text("# Handler example, revised\n")
        blocked = self.call(*gate, expect=1, issue="FOUNDATION_INCOMPLETE")
        issues = blocked["issues"][0]["actual"]
        skill_issue = next(i for i in issues if i["entity"] == SKILL)
        self.assertEqual(skill_issue["message"], "Skill changed since its agreement")
        self.assertIn(f"roclec foundation agree --ref {SKILL}", skill_issue["remediation"])
        self.assertEqual((skill_issue["expected"], skill_issue["actual"]), (pin, self.pin()))
        self.agree()
        self.call(*gate)
        self.call("change", "start", "CHG-001", "--actor", "Maintainer", "--component", "engine")
        # The approval keeps its original pin; drift from it needed a new agreement, not a new approval.
        self.assertEqual(self.call("inspect", "--change", "CHG-001")["data"]["approval"]["skills"],
                         [{"id": SKILL, "sha256": pin}])
        self.call("check")

    def test_stale_skill_of_another_component_does_not_block_the_gate(self):
        folder = self.skill()
        self.call("reference", "add", SKILL, "--path", LOCATION, "--role", "skill", "--component", "viewer")
        self.agree()
        draft = self.workspace / "draft"
        record = bundle(draft)
        self.call("change", "new", "--file", str(draft / "change.json"))
        self.call("change", "approve", "CHG-001", "--digest", record["proposal_digest"], *ACTOR,
                  *criteria(self.root, "approve"))
        self.call("release", "plan", "engine", "v0.1.0", "--change", "CHG-001")
        (folder / "examples/handler.md").write_text("# Handler example, revised\n")
        self.assertEqual(self.call("inspect", "--reference", SKILL)["data"]["state"], "stale")
        self.call("check", "--change", "CHG-001", "--component", "engine", "--gate", "implement")

    def test_flow_skill_names_must_have_the_reference_shape(self):
        self.assign("implement", ["Bad_Name"])
        self.call("check", expect=2, issue="FLOW_INVALID")

    def test_approval_omits_skills_when_none_apply(self):
        folder = self.skill()
        self.register()  # Engine only: it does not apply to a viewer change, even unreadable.
        os.symlink("SKILL.md", folder / "alias.md")
        draft = self.workspace / "draft"
        record = bundle(draft, components=("viewer",))
        self.call("change", "new", "--file", str(draft / "change.json"))
        self.call("check", "--change", "CHG-001", "--gate", "approve")
        approval = self.call("change", "approve", "CHG-001", "--digest", record["proposal_digest"], *ACTOR,
                             *criteria(self.root, "approve"))["data"]["decision"]
        self.assertNotIn("skills", approval)

    def test_approval_needs_readable_not_agreed_skills(self):
        folder = self.skill()
        self.register(SKILL, "--component", "viewer")
        draft = self.workspace / "draft"
        record = bundle(draft, components=("viewer",))
        self.call("change", "new", "--file", str(draft / "change.json"))
        approve = ("change", "approve", "CHG-001", "--digest", record["proposal_digest"], *ACTOR,
                   *criteria(self.root, "approve"))
        os.symlink("SKILL.md", folder / "alias.md")
        self.call("check", "--change", "CHG-001", "--gate", "approve", expect=2, issue="INVALID_PATH")
        self.call(*approve, expect=2, issue="INVALID_PATH")
        (folder / "alias.md").unlink()
        (folder / "SKILL.md").write_text("")
        self.call("check", "--change", "CHG-001", "--gate", "approve", expect=1, issue="INVALID_REFERENCE")
        self.call(*approve, expect=1, issue="INVALID_REFERENCE")
        (folder / "SKILL.md").write_text("# Conventions\n")
        self.assertEqual(self.call(*approve)["data"]["decision"]["skills"], [{"id": SKILL, "sha256": self.pin()}])
        self.assertEqual(self.call("inspect", "--reference", SKILL)["data"]["state"], "draft")

    def test_skill_pins_are_validated_on_decisions(self):
        self.skill()
        self.register()
        draft = self.workspace / "draft"
        record = bundle(draft)
        self.call("change", "new", "--file", str(draft / "change.json"))
        decision = self.call("change", "approve", "CHG-001", "--digest", record["proposal_digest"], *ACTOR,
                             *criteria(self.root, "approve"))["data"]["decision"]
        path = self.root / f".roclec/decisions/{decision['id']}.json"
        from scripts.c1_scenarios import digest
        for forged_skills in ([], [{"id": SKILL}], [{"id": SKILL, "sha256": "x"}],
                              [{"id": "b", "sha256": "0" * 64}, {"id": "a", "sha256": "0" * 64}]):
            forged = {k: v for k, v in decision.items() if k != "id"} | {"skills": forged_skills}
            forged["id"] = digest(forged)
            path.unlink()
            put_json(self.root / f".roclec/decisions/{forged['id']}.json", forged)
            self.call("check", expect=2, issue="INVALID_INPUT")
            (self.root / f".roclec/decisions/{forged['id']}.json").unlink()
            put_json(path, decision)
        self.call("check")


    def test_interrupted_skill_registration_recovers(self):
        from unittest import mock
        self.skill()
        original = Store._atomic
        calls = []

        def fail_before_receipt(store, relative, content):
            calls.append(relative)
            if relative.startswith(".roclec/receipts/"):
                raise OSError("Injected disk error")
            return original(store, relative, content)

        with mock.patch.object(Store, "_atomic", fail_before_receipt):
            result = invoke(["--project", str(self.root), "--json", "reference", "add", SKILL, "--path", LOCATION,
                             "--role", "skill", "--component", "engine"])
        self.assertEqual(result.returncode, 4, result.stdout)
        payload = json.loads(result.stdout)
        self.assertIn("IO_PARTIAL", codes(payload))
        self.assertIn(".roclec/references.json", calls)
        operation_id = payload["data"]["operation_id"]
        # The guard derives the skill's files from the references.json being written, before and after.
        self.call("operation", "recover", operation_id)
        self.call("check")
        self.assertEqual(self.call("inspect", "--reference", SKILL)["data"]["state"], "draft")

    def test_edited_file_reference_reports_stale(self):
        self.assertEqual(self.call("inspect", "--reference", "context")["data"]["state"], "approved")
        path = self.root / "docs/reference.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nEdited after agreement.\n", encoding="utf-8")
        self.assertEqual(self.call("inspect", "--reference", "context")["data"]["state"], "stale")


def Rejections_root(decision):
    from roclec_spec_kit.model import digest
    subject = decision["subject"]
    return f".roclec/subjects/{subject['type']}/{digest(subject['entity'])}/rejected/{subject['digest']}"


if __name__ == "__main__":
    unittest.main()
