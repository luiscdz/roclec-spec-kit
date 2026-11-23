"""Role briefs of knowledge skills: `inspect --change` skills section and the flow view projection (TK.6)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from roclec_spec_kit.config import load_profile
from roclec_spec_kit.flow import STAGES, parse, render
from roclec_spec_kit.kernel import Kernel
from roclec_spec_kit.knowledge import manifest_digest, skill_files
from scripts.c1_scenarios import bundle, criteria, foundation, init_trunk, profile, tree
try:
    from test_kernel import invoke
except ModuleNotFoundError:  # run as tests.test_skill_brief
    from tests.test_kernel import invoke

FLOW = ".roclec/flow.toml"
ACTOR = ("--actor", "Maintainer", "--reason", "Reviewed")


class SkillBriefTest(unittest.TestCase):
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

    def call(self, *args, expect=0):
        before = tree(self.root)
        result = invoke(["--project", str(self.root), "--json", *args])
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        if expect in (1, 2, 3):
            self.assertEqual(tree(self.root), before, "Rejected operation mutated consumer")
        return json.loads(result.stdout)

    def skill(self, name):
        folder = self.root / ".agents/skills" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(f"---\nname: {name}\n---\n\n# {name}\n", encoding="utf-8")
        return folder

    def register(self, name, *components):
        self.skill(name)
        self.call("reference", "add", name, "--path", f".agents/skills/{name}", "--role", "skill",
                  *(arg for c in components for arg in ("--component", c)))

    def agree(self, name):
        self.call("foundation", "agree", "--ref", name, *ACTOR, *criteria(self.root, "foundation"))

    def pin(self, name):
        return manifest_digest(skill_files(self.root, f".agents/skills/{name}"))

    def assign(self, stage, names):
        path = self.root / FLOW
        text = path.read_text(encoding="utf-8")
        header = f"[stages.{stage}]\n"
        self.assertEqual(text.count(header), 1)
        path.write_text(text.replace(header, header + f"skills = {json.dumps(names)}\n"), encoding="utf-8")

    def brief(self):
        return self.call("inspect", "--change", "CHG-001")["data"]["skills"]

    def stale_view(self):
        return [i for i in self.call("check")["issues"] if i["code"] == "FLOW_VIEW_STALE"]

    def test_inspect_change_lists_pinned_current_and_drift_per_component_and_stage(self):
        self.register("alpha", "engine")
        self.register("beta", "engine", "viewer")
        self.assign("implement", ["alpha"])
        self.assign("review", ["alpha"])
        for name in ("alpha", "beta", "flow"):
            self.agree(name)
        draft = self.workspace / "draft"
        record = bundle(draft)
        self.call("change", "new", "--file", str(draft / "change.json"))
        before = self.brief()
        # Before approval: nothing pinned, nothing drifted; the stage-restricted skill only where listed.
        self.assertEqual(sorted(before), ["engine", "viewer"])
        self.assertEqual(sorted(before["engine"]), sorted(STAGES))  # beta applies at every stage.
        # JSON output sorts keys; the kernel's mapping keeps flow order.
        kernel = Kernel(load_profile(self.root))
        self.assertEqual(list(kernel.inspect_change("CHG-001")["skills"]["engine"]), list(STAGES))
        self.assertEqual([r["id"] for r in before["engine"]["implement"]], ["alpha", "beta"])
        self.assertEqual([r["id"] for r in before["engine"]["review"]], ["alpha", "beta"])
        self.assertEqual([r["id"] for r in before["engine"]["verify"]], ["beta"])
        self.assertEqual({stage: [r["id"] for r in rows] for stage, rows in before["viewer"].items()},
                         {stage: ["beta"] for stage in STAGES})
        alpha = before["engine"]["implement"][0]
        self.assertEqual(alpha, {"id": "alpha", "path": ".agents/skills/alpha", "sha256": self.pin("alpha"),
                                 "pinned": None, "drift": False, "state": "approved"})

        self.call("change", "approve", "CHG-001", "--digest", record["proposal_digest"], *ACTOR,
                  *criteria(self.root, "approve"))
        pins = {name: self.pin(name) for name in ("alpha", "beta")}
        approved = self.brief()
        self.assertEqual(approved["engine"]["implement"],
                         [{"id": name, "path": f".agents/skills/{name}", "sha256": pins[name], "pinned": pins[name],
                           "drift": False, "state": "approved"} for name in ("alpha", "beta")])

        # Editing a skill after approval: current differs from the pin, the reference is stale.
        (self.root / ".agents/skills/alpha/SKILL.md").write_text("---\nname: alpha\n---\n\n# Revised\n", encoding="utf-8")
        before_inspect = tree(self.root)
        drifted = self.brief()
        self.assertEqual(tree(self.root), before_inspect, "inspect wrote")
        for stage in ("implement", "review"):
            row = drifted["engine"][stage][0]
            self.assertEqual((row["id"], row["sha256"], row["pinned"], row["drift"], row["state"]),
                             ("alpha", self.pin("alpha"), pins["alpha"], True, "stale"))
            self.assertNotEqual(row["sha256"], row["pinned"])
        self.assertFalse(drifted["engine"]["implement"][1]["drift"])
        self.assertEqual(drifted["viewer"]["implement"][0]["state"], "approved")

        # Reagreeing makes the reference current again; the approval keeps its pin, so drift remains visible.
        self.agree("alpha")
        row = self.brief()["engine"]["implement"][0]
        self.assertEqual((row["state"], row["drift"], row["pinned"]), ("approved", True, pins["alpha"]))

    def test_components_without_skills_and_missing_flow(self):
        self.register("alpha", "engine")
        draft = self.workspace / "draft"
        bundle(draft)
        self.call("change", "new", "--file", str(draft / "change.json"))
        brief = self.brief()
        self.assertEqual(brief["viewer"], {})
        self.assertEqual(brief["engine"]["define"][0]["state"], "draft")
        # Not approved: nothing pinned.
        self.assertIsNone(brief["engine"]["define"][0]["pinned"])
        # A missing flow: the section is null, inspect still answers and the flow section reports why.
        (self.root / FLOW).unlink()
        data = self.call("inspect", "--change", "CHG-001")["data"]
        self.assertIsNone(data["skills"])
        self.assertEqual(data["flow"]["error"]["code"], "FLOW_MISSING")
        self.assertNotIn("FLOW_MISSING", [i["code"] for i in data["issues"]])
        # Lists of changes do not compute briefs.
        self.assertEqual([c["id"] for c in self.call("list", "changes")["data"]["changes"]], ["CHG-001"])

    def test_unsafe_skill_nulls_the_section_without_failing_inspect(self):
        folder = self.skill("alpha")
        self.call("reference", "add", "alpha", "--path", ".agents/skills/alpha", "--role", "skill",
                  "--component", "engine")
        draft = self.workspace / "draft"
        bundle(draft)
        self.call("change", "new", "--file", str(draft / "change.json"))
        os.symlink(folder / "SKILL.md", folder / "linked.md")
        before = tree(self.root)
        data = self.call("inspect", "--change", "CHG-001")["data"]
        self.assertEqual(tree(self.root), before, "inspect wrote")
        self.assertIsNone(data["skills"])
        self.assertIn("INVALID_PATH", [i["code"] for i in data["issues"]])

    def test_flow_view_lists_skills_by_stage_and_goes_stale_on_registration(self):
        self.call("views", "--write")
        self.assertEqual(self.stale_view(), [])
        view = self.root / "docs/flow.md"
        self.assertNotIn("## Knowledge skills", view.read_text(encoding="utf-8"))

        self.register("alpha", "engine")
        stale = self.stale_view()
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["actual"], "stale")
        self.call("views", "--write")
        self.assertEqual(self.stale_view(), [])
        text = view.read_text(encoding="utf-8")
        self.assertIn("## Knowledge skills", text)
        self.assertIn("| `alpha` | [.agents/skills/alpha](../.agents/skills/alpha) | engine | every stage |", text)
        self.assertIn("| implement | `alpha` (engine) |", text)

        # A stage restriction in the flow changes the projection: stale until regenerated.
        self.register("beta", "engine", "viewer")
        self.assign("implement", ["alpha"])
        self.assertEqual(len(self.stale_view()), 1)
        self.call("views", "--write")
        self.assertEqual(self.stale_view(), [])
        text = view.read_text(encoding="utf-8")
        self.assertIn("| `alpha` | [.agents/skills/alpha](../.agents/skills/alpha) | engine | implement |", text)
        self.assertIn("| `beta` | [.agents/skills/beta](../.agents/skills/beta) | engine, viewer | every stage |", text)
        self.assertIn("| implement | `alpha` (engine)<br>`beta` (engine, viewer) |", text)
        self.assertIn("| verify | `beta` (engine, viewer) |", text)

        # Changing a skill's components is a registration change too.
        self.call("reference", "update", "beta", "--path", ".agents/skills/beta", "--role", "skill",
                  "--component", "viewer")
        self.assertEqual(len(self.stale_view()), 1)
        self.call("views", "--write")
        self.assertIn("| verify | `beta` (viewer) |", view.read_text(encoding="utf-8"))
        self.assertEqual(self.stale_view(), [])

    def test_render_without_skills_keeps_its_bytes(self):
        parsed = parse((self.root / FLOW).read_bytes())
        data = load_profile(self.root).data
        self.assertEqual(render(parsed, data), render(parsed, data, None, []))
        with_skill = render(parsed, data, None, [{"id": "alpha", "path": ".agents/skills/alpha", "components": ["engine"]}])
        self.assertNotEqual(render(parsed, data), with_skill)
        # The kernel's own inputs for a project without skills render today's bytes.
        flow, _, _, _, inputs = Kernel(load_profile(self.root))._flow_view(learning=True)
        self.assertEqual(inputs["skills"], [])
        self.assertEqual(render(flow, data, **inputs), render(flow, data, inputs["learning"]))


if __name__ == "__main__":
    unittest.main()
