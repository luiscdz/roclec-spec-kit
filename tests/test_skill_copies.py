"""Knowledge-skill host copies, divergence and unregistered skills (TK.3), and candidate classification."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from roclec_spec_kit.config import load_profile
from roclec_spec_kit.installation import _native
from roclec_spec_kit.kernel import Kernel
from roclec_spec_kit.knowledge import skill_files
from roclec_spec_kit.model import ModelError, sha
from roclec_spec_kit.verification import Verification
from scripts.c1_scenarios import criteria, foundation, init_trunk, profile, tree
from scripts.c2_scenarios import setup
try:
    from test_kernel import invoke
except ModuleNotFoundError:  # run as tests.test_skill_copies
    from tests.test_kernel import invoke

SKILL = "conventions"
CANONICAL = f".agents/skills/{SKILL}"
COPY = f".claude/skills/{SKILL}"
FILES = {"SKILL.md": f"---\nname: {SKILL}\n---\n\n# Conventions\n", "examples/handler.md": "# Handler example\n",
         ".hidden": "hidden rule\n", "examples/nested/.rule": "deep hidden rule\n"}


def codes(payload):
    return [i["code"] for i in payload["issues"]]


def write_skill(root, name=SKILL, files=None):
    folder = root / ".agents/skills" / name
    for relative, body in (files or FILES).items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return folder


class SkillCopyTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)
        self.root = self.workspace / "project"
        config = self.workspace / "profile.toml"
        profile(config)
        init_trunk(self.root)
        result = invoke(["--json", "init", str(self.root), "--profile", str(config)])
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

    def register(self, name=SKILL):
        return self.call("reference", "add", name, "--path", f".agents/skills/{name}", "--role", "skill",
                         "--component", "engine")

    def warnings(self, code):
        return [i for i in self.call("check")["issues"] if i["code"] == code]

    def files(self, relative):
        return skill_files(self.root, relative)

    def manifest(self):
        return json.loads((self.root / ".roclec/installation.json").read_text(encoding="utf-8"))

    def test_copy_matches_canonical_byte_for_byte_and_is_recorded(self):
        write_skill(self.root)
        self.register()  # Registered, not agreed: still copied.
        canonical_before = tree(self.root / ".agents/skills")
        self.call("skills")
        self.assertEqual(self.files(COPY), self.files(CANONICAL))
        self.assertEqual(sorted(self.files(COPY)), sorted(FILES))
        self.assertFalse((self.root / ".agents/skills" / SKILL / ".roclec").exists())
        self.assertEqual({k: v for k, v in tree(self.root / ".agents/skills").items() if k.startswith(SKILL)},
                         {k: v for k, v in canonical_before.items() if k.startswith(SKILL)}, "canonical never written")
        manifest = self.manifest()
        for inner, data in self.files(CANONICAL).items():
            relative = f"{COPY}/{inner}"
            self.assertEqual(manifest["files"][relative], sha(data))
            self.assertIn(relative, manifest["managed"])
        self.assertFalse(any(p.startswith(CANONICAL) for p in manifest["files"]))
        self.assertEqual(self.warnings("SKILL_COPY_DIVERGED"), [])
        self.assertEqual(self.warnings("SKILL_UNREGISTERED"), [])
        self.call("skills")  # An unchanged refresh is accepted.
        self.assertEqual(self.files(COPY), self.files(CANONICAL))

    def test_divergence_edit_refusal_restore_and_canonical_updates(self):
        folder = write_skill(self.root)
        self.register()
        missing = self.warnings("SKILL_COPY_DIVERGED")
        self.assertEqual([(w["severity"], w["entity"], w["path"]) for w in missing], [("warning", SKILL, COPY)])
        self.assertEqual((missing[0]["actual"], missing[0]["expected"]), ("missing", CANONICAL))
        self.assertIn("roclec skills", missing[0]["remediation"])
        self.call("skills")
        copy = self.root / COPY / "SKILL.md"
        original = copy.read_bytes()
        copy.write_text("# Edited only in the copy\n", encoding="utf-8")
        diverged = self.warnings("SKILL_COPY_DIVERGED")
        self.assertEqual([(w["actual"], w["expected"]) for w in diverged], [(["SKILL.md"], CANONICAL)])
        self.assertIn(f"Edit only {CANONICAL}/", diverged[0]["remediation"])
        refused = self.call("skills", expect=1, issue="MANAGED_FILE_EDITED")
        self.assertEqual(refused["issues"][0]["actual"], [f"{COPY}/SKILL.md"])
        copy.write_bytes(original)
        self.call("skills")
        self.assertEqual(self.warnings("SKILL_COPY_DIVERGED"), [])
        # The canonical directory drives the copy: edits, additions and deletions.
        (folder / "SKILL.md").write_text("# Revised conventions\n", encoding="utf-8")
        (folder / "examples/added.md").write_text("# Added\n", encoding="utf-8")
        self.assertEqual(self.warnings("SKILL_COPY_DIVERGED")[0]["actual"], ["SKILL.md", "examples/added.md"])
        self.call("skills")
        self.assertEqual(self.files(COPY), self.files(CANONICAL))
        (folder / "examples/nested/.rule").unlink()
        (folder / "examples/nested").rmdir()
        self.call("skills")
        self.assertFalse((self.root / COPY / "examples/nested").exists(), "retired file and its empty folder")
        self.assertEqual(self.files(COPY), self.files(CANONICAL))
        self.assertNotIn(f"{COPY}/examples/nested/.rule", self.manifest()["files"])
        # An edited copy of a file dropped from the canonical directory is refused, not deleted.
        (self.root / COPY / "examples/added.md").write_text("# Edited copy\n", encoding="utf-8")
        (folder / "examples/added.md").unlink()
        refused = self.call("skills", expect=1, issue="MANAGED_FILE_EDITED")
        self.assertEqual(refused["issues"][0]["actual"], [f"{COPY}/examples/added.md"])
        (self.root / COPY / "examples/added.md").write_text("# Added\n", encoding="utf-8")
        self.call("skills")
        self.assertFalse((self.root / COPY / "examples/added.md").exists())

    def test_extra_and_unrecorded_copy_files_are_reported_never_overwritten(self):
        write_skill(self.root)
        self.register()
        self.call("skills")
        extra = self.root / COPY / "extra.md"
        extra.write_text("# Only in the copy\n", encoding="utf-8")
        self.assertEqual(self.warnings("SKILL_COPY_DIVERGED")[0]["actual"], ["extra.md"])
        self.call("skills")
        self.assertTrue(extra.is_file(), "a file Roclec never recorded is not pruned")
        extra.unlink()
        # A different pre-existing copy that Roclec did not record is consumer content.
        write_skill(self.root, "second")
        self.register("second")
        (self.root / ".claude/skills/second").mkdir(parents=True)
        (self.root / ".claude/skills/second/SKILL.md").write_text("# Consumer copy\n", encoding="utf-8")
        self.call("skills", expect=1, issue="UNMANAGED_FILE")
        # An identical pre-existing file is adopted.
        shutil.copyfile(self.root / ".agents/skills/second/SKILL.md", self.root / ".claude/skills/second/SKILL.md")
        self.call("skills")
        self.assertEqual(self.files(".claude/skills/second"), self.files(".agents/skills/second"))

    def test_symlink_in_canonical_skill_fails_before_writing(self):
        folder = write_skill(self.root)
        self.register()
        (self.root / "shared.md").write_text("# Shared\n", encoding="utf-8")
        os.symlink(self.root / "shared.md", folder / "linked.md")
        failed = self.call("skills", expect=2, issue="INVALID_PATH")
        self.assertEqual(failed["issues"][0]["path"], f"{CANONICAL}/linked.md")
        self.assertFalse((self.root / COPY).exists())
        self.assertFalse((self.root / ".roclec/installation.json").exists())

    def test_unregistered_skills_warn_once_without_blocking(self):
        self.call("skills")
        self.assertEqual(self.warnings("SKILL_UNREGISTERED"), [], "roclec-* skills are Roclec's")
        write_skill(self.root, "foo", {"SKILL.md": "# Foo\n"})
        (self.root / ".claude/skills/foo").mkdir(parents=True)
        (self.root / ".claude/skills/foo/SKILL.md").write_text("# Foo\n", encoding="utf-8")
        (self.root / ".agents/skills/notes").mkdir()  # No SKILL.md: not a skill.
        (self.root / ".agents/skills/speckit-plan").mkdir()
        (self.root / ".agents/skills/speckit-plan/SKILL.md").write_text("# Adapter\n", encoding="utf-8")
        write_skill(self.root, "external", {"SKILL.md": "# External\n"})
        (self.root / "skills-lock.json").write_text(json.dumps({"version": 1, "skills": {"external": {
            "source": "example/skills", "sourceType": "github", "skillPath": "skills/external/SKILL.md",
            "computedHash": "0" * 64}}}), encoding="utf-8")
        found = self.warnings("SKILL_UNREGISTERED")
        self.assertEqual([(w["entity"], w["severity"], w["actual"]) for w in found],
                         [("foo", "warning", [".agents/skills/foo", ".claude/skills/foo"])])
        self.assertIn("reference add foo --path .agents/skills/foo --role skill", found[0]["remediation"])
        self.register("foo")
        self.assertEqual(self.warnings("SKILL_UNREGISTERED"), [])

    def test_unregistered_skill_only_in_the_claude_host_is_reported(self):
        folder = self.root / COPY
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("# Claude only\n", encoding="utf-8")
        found = self.warnings("SKILL_UNREGISTERED")
        self.assertEqual([(w["entity"], w["path"], w["actual"]) for w in found], [(SKILL, COPY, [COPY])])
        self.assertIn(f"reference add {SKILL} --path {CANONICAL} --role skill", found[0]["remediation"])

    def test_deregistered_skill_copy_stays_and_is_reported(self):
        write_skill(self.root)
        self.register()
        self.call("skills")
        self.assertIn(f"{COPY}/SKILL.md", self.manifest()["managed"])
        before = self.files(COPY)
        # Only a hand edit of references.json can deregister a directory reference today.
        path = self.root / ".roclec/references.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["references"] = [r for r in data["references"] if r["id"] != SKILL]
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.call("skills")
        # Roclec no longer owns the copy: it stays on disk, leaves the manifest and is reported.
        self.assertEqual(self.files(COPY), before)
        self.assertFalse([p for p in self.manifest()["managed"] if p.startswith(COPY + "/")])
        self.assertEqual([w["entity"] for w in self.warnings("SKILL_UNREGISTERED")], [SKILL])

    def test_native_rule_covers_only_copies_of_registered_skills(self):
        skills = frozenset({SKILL})
        self.assertTrue(_native(f"{COPY}/SKILL.md", skills))
        self.assertTrue(_native(f"{COPY}/examples/handler.md", skills))
        for relative in (f"{CANONICAL}/SKILL.md", ".claude/skills/other/SKILL.md", COPY, f".claude/skills/{SKILL}",
                         f".codex/skills/{SKILL}/SKILL.md"):
            self.assertFalse(_native(relative, skills), relative)
        self.assertFalse(_native(f"{COPY}/SKILL.md"), "unregistered without the reference set")


class SkillCandidateClassificationTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root, self.base = setup(Path(temp.name) / "copies", invoke)

    def call(self, *args):
        result = invoke(["--project", str(self.root), "--json", *args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_skill_files_are_inputs_of_its_components_and_copies_operational(self):
        folder = write_skill(self.root, files={"SKILL.md": "# Conventions\n", "examples/handler.md": "# Handler\n"})
        self.call("reference", "add", SKILL, "--path", CANONICAL, "--role", "skill", "--component", "engine")
        self.call("foundation", "agree", "--ref", SKILL, "--actor", "Maintainer", "--reason", "Agreed",
                  *criteria(self.root, "foundation"))
        shutil.copytree(folder, self.root / COPY)
        (folder / "examples/handler.md").write_text("# Handler, revised in this change\n", encoding="utf-8")
        shutil.copytree(folder, self.root / COPY, dirs_exist_ok=True)
        self.call("foundation", "agree", "--ref", SKILL, "--actor", "Maintainer", "--reason", "Re-agreed",
                  *criteria(self.root, "foundation"))
        verifier = Verification(Kernel(load_profile(self.root)))
        categories = verifier.candidate("CHG-001", "engine", self.base)["categories"]
        for inner in ("SKILL.md", "examples/handler.md"):
            self.assertEqual(categories[f"{CANONICAL}/{inner}"], "input")
            self.assertEqual(categories[f"{COPY}/{inner}"], "operational")
        candidate = verifier.candidate("CHG-001", "engine", self.base)
        self.assertIn(f"{CANONICAL}/examples/handler.md", candidate["inputs"]["files"])
        self.assertNotIn(f"{COPY}/examples/handler.md", candidate["inputs"]["files"])
        # The skill does not name viewer: its files are not viewer inputs (classified by the profile, here unknown).
        with self.assertRaises(ModelError) as caught:
            verifier.candidate("CHG-001", "viewer", self.base)
        self.assertEqual(caught.exception.issue["code"], "CANDIDATE_INCOMPLETE")
        self.assertEqual(caught.exception.issue["actual"], [f"{CANONICAL}/SKILL.md", f"{CANONICAL}/examples/handler.md"])


if __name__ == "__main__":
    unittest.main()
