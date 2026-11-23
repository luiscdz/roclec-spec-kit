"""Authority map in the managed block of AGENTS.md/CLAUDE.md and its staleness warning (TK.4)."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from roclec_spec_kit import instructions
from roclec_spec_kit.config import load_profile
from roclec_spec_kit.kernel import Kernel
from roclec_spec_kit.model import ModelError
from roclec_spec_kit.store import Store
from scripts.c1_scenarios import adr_markdown, criteria, foundation, init_trunk, profile, tree
try:
    from test_kernel import invoke
except ModuleNotFoundError:  # run as tests.test_authority_map
    from tests.test_kernel import invoke

BEFORE = "# Team rules\n\nRun the project tests.\n"
AFTER = "\n## Local notes\n\nKeep this paragraph.\n"
ACTOR = ("--actor", "Maintainer", "--reason", "Reviewed")
FLOW = ".roclec/flow.toml"


def codes(payload):
    return [i["code"] for i in payload["issues"]]


class AuthorityMapTest(unittest.TestCase):
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

    def stale(self):
        return [(i["path"], i["severity"]) for i in self.call("check")["issues"] if i["code"] == "AGENT_INSTRUCTIONS_STALE"]

    def block(self, name="AGENTS.md"):
        body = (self.root / name).read_text(encoding="utf-8")
        before, block, after = instructions.split(body, name)
        return before, block, after

    def install(self):
        (self.root / "AGENTS.md").write_text(BEFORE, encoding="utf-8")
        self.call("skills")
        path = self.root / "AGENTS.md"
        path.write_text(path.read_text(encoding="utf-8") + AFTER, encoding="utf-8")

    def skill(self, name):
        folder = self.root / ".agents/skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        self.call("reference", "add", name, "--path", f".agents/skills/{name}", "--role", "skill", "--component", "engine")

    def agree(self, ref_id):
        self.call("foundation", "agree", "--ref", ref_id, *ACTOR, *criteria(self.root, "foundation"))

    def adr(self, adr_id, *supersedes):
        path = self.root / "docs/adr" / f"{adr_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(adr_markdown(f"{adr_id}: Decision"), encoding="utf-8")
        extra = [arg for older in supersedes for arg in ("--supersedes", older)]
        self.call("reference", "add", adr_id, "--path", f"docs/adr/{adr_id}.md", "--component", "engine",
                  "--role", "decision", *extra)

    def assign(self, stage, names):
        path = self.root / FLOW
        text = path.read_text(encoding="utf-8")
        header = f"[stages.{stage}]\n"
        path.write_text(text.replace(header, header + f"skills = {json.dumps(names)}\n"), encoding="utf-8")

    def test_block_lists_agreed_authorities_and_preserves_consumer_text(self):
        self.install()
        before, block, after = self.block()
        self.assertEqual((before, after), (BEFORE + "\n\n", "\n" + AFTER))
        self.assertIn(instructions.routing(), block)
        lines = block.splitlines()
        self.assertIn("References by role:", lines)
        self.assertIn("- architecture `architecture`: [docs/reference.md](docs/reference.md); components: all components",
                      lines)
        self.assertIn("- process `flow`: [.roclec/flow.toml](.roclec/flow.toml); components: all components", lines)
        self.assertNotIn("ADRs:", lines)
        self.assertEqual(self.stale(), [])
        self.assertEqual(self.block("CLAUDE.md")[1], block)
        # Registered but never agreed: not listed, so the block stays current.
        self.adr("ADR-001")
        self.skill("api-style")
        self.assertEqual(self.stale(), [])
        for ref_id in ("ADR-001", "api-style"):
            self.assertNotIn(f"`{ref_id}`", self.block()[1], "the map lists only agreed entries")
        self.agree("ADR-001")
        self.agree("api-style")
        self.assertEqual(self.stale(), [("AGENTS.md", "warning"), ("CLAUDE.md", "warning")])
        failed = self.call("views", expect=1, issue="VIEW_STALE")
        self.assertIn("AGENTS.md", failed["issues"][0]["actual"])
        self.assertIn("CLAUDE.md", failed["issues"][0]["actual"])
        written = self.call("views", "--write")["data"]["written"]
        self.assertIn("AGENTS.md", written)
        self.assertEqual(self.stale(), [])
        before, block, after = self.block()
        self.assertEqual((before, after), (BEFORE + "\n\n", "\n" + AFTER), "text outside the block is unchanged")
        lines = block.splitlines()
        self.assertIn("- `ADR-001`: [docs/adr/ADR-001.md](docs/adr/ADR-001.md); components: engine", lines)
        self.assertIn("- `api-style`: [.agents/skills/api-style](.agents/skills/api-style); components: engine; "
                      "stages: every stage", lines)
        # A superseding ADR hides the one it supersedes once agreed.
        self.adr("ADR-002", "ADR-001")
        self.agree("ADR-002")
        self.call("views", "--write")
        block = self.block()[1]
        self.assertNotIn("`ADR-001`", block)
        self.assertIn("`ADR-002`", block)
        # Stage assignment in flow.toml is part of the map.
        self.assign("implement", ["api-style"])
        self.assign("review", ["api-style"])
        self.assertEqual(self.stale(), [("AGENTS.md", "warning"), ("CLAUDE.md", "warning")])
        self.call("skills")  # `skills` regenerates it too.
        self.assertEqual(self.stale(), [])
        self.assertIn("components: engine; stages: implement, review", self.block()[1])
        self.assertEqual(self.block()[0], BEFORE + "\n\n")
        kernel = Kernel(load_profile(self.root))
        self.assertEqual(kernel.instruction_block(), self.block()[1], "the block is the kernel's pure generation")

    def test_empty_map_and_files_without_a_block(self):
        (self.root / ".roclec/references.json").write_text(json.dumps({"model_schema": 2, "references": []}),
                                                           encoding="utf-8")
        self.call("skills")
        block = self.block()[1]
        self.assertIn(instructions.EMPTY, block)
        self.assertNotIn(instructions.RULE, block)
        (self.root / "CLAUDE.md").write_text("# No Roclec block here\n", encoding="utf-8")
        self.skill("api-style")
        self.agree("api-style")
        self.assertEqual(self.stale(), [("AGENTS.md", "warning")])
        self.call("views", "--write")
        self.assertEqual((self.root / "CLAUDE.md").read_text(encoding="utf-8"), "# No Roclec block here\n",
                         "views --write never adds a block")
        self.assertEqual(self.stale(), [])
        self.call("skills")
        self.assertEqual(self.block("CLAUDE.md")[1], self.block()[1], "skills adds it")

    def test_malformed_block_warns_and_refuses_regeneration(self):
        self.call("skills")
        path = self.root / "AGENTS.md"
        path.write_text(path.read_text(encoding="utf-8") + instructions.START + "\n", encoding="utf-8")
        warned = [i for i in self.call("check")["issues"] if i["code"] == "UNMANAGED_FILE"]
        self.assertEqual([(w["path"], w["actual"]) for w in warned], [("AGENTS.md", "malformed")])
        self.call("views", "--write", expect=1, issue="UNMANAGED_FILE")
        self.call("skills", expect=1, issue="UNMANAGED_FILE")

    def test_non_utf8_instruction_file_warns_and_refuses_regeneration(self):
        self.call("skills")
        (self.root / "AGENTS.md").write_bytes(b"# Team rules \xff\xfe\n")
        warned = [i for i in self.call("check")["issues"] if i["code"] == "UNMANAGED_FILE"]
        self.assertEqual([(w["path"], w["severity"], w["actual"]) for w in warned],
                         [("AGENTS.md", "warning", "not-utf8")])
        self.call("views", "--write", expect=1, issue="UNMANAGED_FILE")
        self.call("skills", expect=1, issue="UNMANAGED_FILE")
        self.assertEqual((self.root / "AGENTS.md").read_bytes(), b"# Team rules \xff\xfe\n")

    def test_recovery_refuses_a_consumer_edit_outside_the_block(self):
        from unittest import mock
        self.install()
        self.skill("api-style")
        self.agree("api-style")
        original = Store._atomic

        def fail_on_instructions(store, relative, content):
            if relative == "AGENTS.md":
                raise OSError("Injected disk error")
            return original(store, relative, content)

        with mock.patch.object(Store, "_atomic", fail_on_instructions):
            result = invoke(["--project", str(self.root), "--json", "views", "--write"])
        self.assertEqual(result.returncode, 4, result.stdout)
        operation_id = json.loads(result.stdout)["data"]["operation_id"]
        path = self.root / "AGENTS.md"
        edited = path.read_text(encoding="utf-8").replace("Keep this paragraph.", "Consumer edit made meanwhile.")
        path.write_text(edited, encoding="utf-8")
        # An edit outside the block makes the destination diverge from the journal: refused before any write.
        # (The block-only guard itself needs a forged journal; the destination check always trips first.)
        self.call("operation", "recover", operation_id, expect=3, issue="OPERATION_CONFLICT")
        self.assertEqual(path.read_text(encoding="utf-8"), edited)

    def test_invalid_flow_does_not_block_skills_install(self):
        self.install()
        self.skill("conventions")
        self.agree("conventions")
        self.call("skills")
        flow = self.root / FLOW
        valid = flow.read_bytes()
        flow.write_bytes(b"this is not toml [[[\n")
        # The installer does not depend on the flow it does not own: every agreed skill lists every stage.
        self.call("skills")
        self.assertIn("every stage", self.block()[1])
        self.assertEqual(flow.read_bytes(), b"this is not toml [[[\n")
        self.assertIn("FLOW_INVALID", codes(self.call("check", expect=2)))
        flow.write_bytes(valid)
        self.call("views", "--write")
        self.assertEqual(self.stale(), [])

    def test_store_lets_views_rewrite_only_the_block(self):
        self.install()
        store = Store(self.root)
        body = (self.root / "AGENTS.md").read_bytes()
        for payload, content in (({}, body + b"x"),
                                 ({"instructions": ["AGENTS.md"]}, b"overwrite"),
                                 ({"instructions": ["AGENTS.md"]}, body.replace(b"Team rules", b"Rewritten")),
                                 ({"instructions": ["README.md"]}, body),
                                 ({"instructions": ["CLAUDE.md", "AGENTS.md"]}, body + b"x")):
            with self.subTest(payload=payload), self.assertRaises(ModelError) as caught:
                store.apply("views", payload, {"AGENTS.md": content}, store.token())
            self.assertEqual(caught.exception.issue["code"], "OPERATION_CONFLICT")
            self.assertEqual((self.root / "AGENTS.md").read_bytes(), body)
        before, block, after = self.block()
        rewritten = (before + block.replace("Authority map", "Authority map (edited)") + after).encode("utf-8")
        store.apply("views", {"instructions": ["AGENTS.md"]}, {"AGENTS.md": rewritten}, store.token())
        self.assertEqual((self.root / "AGENTS.md").read_bytes(), rewritten)


class LinkedRepoBlockTest(unittest.TestCase):
    def test_linked_repo_block_points_to_the_project_root_map(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            root, code = workspace / "project", workspace / "code"
            config = workspace / "profile.toml"
            profile(config, names=("engine",), repo="../code")
            init_trunk(root)
            init_trunk(code)
            result = invoke(["--json", "init", str(root), "--profile", str(config)])
            self.assertEqual(result.returncode, 0, result.stdout)
            result = invoke(["--project", str(root), "--json", "skills", "--into", "engine"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in instructions.FILES:
                block = instructions.split((code / name).read_text(encoding="utf-8"), name)[1]
                self.assertEqual(block, instructions.linked_block("../project", name))
                self.assertIn(f"`../project/{name}`", block)
            self.assertFalse((code / ".claude/skills").exists() and any(
                p.name not in () and not p.name.startswith("roclec-") for p in (code / ".claude/skills").iterdir()))


if __name__ == "__main__":
    unittest.main()
