"""Per-stage conformance in `inspect --change` (TF.7, section 7.6)."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from roclec_spec_kit.flow import STAGES
from roclec_spec_kit.model import sha
from scripts.c1_scenarios import bundle, criteria, declare_hook, file_hash, foundation, init_trunk, profile, put_json, tree
try:
    from test_kernel import invoke
except ModuleNotFoundError:  # run as tests.test_flow_conformance
    from tests.test_kernel import invoke

FLOW = ".roclec/flow.toml"
ACTOR = ("--actor", "Owner", "--reason", "Reviewed")


class FlowConformanceTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)
        self.project("project")

    def project(self, name, prototype=None):
        """A consumer with CHG-001 imported; viewer is user-facing so the design stage applies to it."""
        self.root = self.workspace / name
        init_trunk(self.root)
        config = self.workspace / f"{name}.toml"
        profile(config)
        text = config.read_text().split("[components.viewer]")
        config.write_text(text[0] + "[components.viewer]" + text[1].replace("user_facing = false", "user_facing = true", 1))
        result = invoke(["--json", "init", str(self.root), "--profile", str(config)])
        self.assertEqual(result.returncode, 0, result.stdout)
        foundation(self.root)
        folder = self.workspace / f"{name}-draft"
        self.record = bundle(folder)
        if prototype:
            path = self.root / prototype
            path.parent.mkdir(parents=True)
            path.write_text("<h1>Screen</h1>\n")
            self.record["semantic"]["prototypes"] = [{"path": prototype}]
            put_json(folder / "change.json", self.record)
            self.call("change", "seal", folder)
            self.record = json.loads((folder / "change.json").read_text())
        self.call("change", "new", "--file", folder / "change.json")

    def call(self, *args, expect=0, issue=None):
        before = tree(self.root)
        result = invoke(["--project", str(self.root), "--json", *map(str, args)])
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        if issue:
            self.assertIn(issue, [i["code"] for i in payload["issues"]], result.stdout)
        if expect in (1, 2, 3):
            self.assertEqual(tree(self.root), before, "Rejected operation mutated consumer")
        return payload

    def inspect(self):
        before = tree(self.root)
        data = self.call("inspect", "--change", "CHG-001")["data"]
        self.assertEqual(tree(self.root), before, "inspect must not write")
        return data

    def stages(self, data=None):
        data = data or self.inspect()
        return {row["stage"]: row for row in data["flow"]["stages"]}

    def approve(self):
        return self.call("change", "approve", "CHG-001", "--digest", self.record["proposal_digest"], *ACTOR,
                         *criteria(self.root, "approve"))["data"]["decision"]

    def plan(self):
        self.call("release", "plan", "engine", "v0.1.0", "--change", "CHG-001")
        self.call("release", "plan", "viewer", "v0.1.0", "--change", "CHG-001")

    def test_stages_follow_the_flow_and_mark_the_human_stage_limitation(self):
        data = self.inspect()
        flow = data["flow"]
        self.assertEqual(flow["sha256"], sha((self.root / FLOW).read_bytes()))
        self.assertEqual((flow["agreed"], flow["agreement_issues"], flow["approved_under"]), (True, [], None))
        stages = self.stages(data)
        self.assertEqual(list(stages), list(STAGES))
        for name, row in stages.items():
            self.assertEqual("limitation" in row, row["ai"] is False, name)
            self.assertEqual("reason" in row, row["ai"] is False, name)
        approve = stages["approve"]
        self.assertIn("cannot prove", approve["limitation"])
        self.assertEqual(approve["checkpoint"], {"decider": "owner", "criteria": ["CR-002", "CR-003"],
                                                 "on_reject": "revise", "hook": None})
        self.assertEqual(approve["change"], {
            "status": "pending", "record": None, "actor": None, "criteria": [], "sessions": [],
            "pending": {"decider": "owner", "criteria": [
                {"id": "CR-002", "text": "Every origin criterion is covered, excluded or deferred."},
                {"id": "CR-003", "text": "The proposal states the intended behavior."}]}})
        self.assertEqual(stages["define"]["change"]["record"], self.record["proposal_digest"])
        self.assertTrue(stages["define"]["change"]["sealed"])
        foundation = stages["foundation"]["components"]["engine"]
        self.assertEqual(foundation["status"], "done")
        self.assertIn("flow", foundation["agreed"])
        # viewer is user-facing: it still lacks an agreed design reference, presented to the decider.
        viewer = stages["foundation"]["components"]["viewer"]
        self.assertEqual(viewer["status"], "pending")
        self.assertEqual(viewer["pending"]["criteria"], [{"id": "CR-001", "text": "The reference reflects the practice the user agreed."}])
        self.assertTrue(any("design" in issue["message"] for issue in viewer["issues"]))
        self.assertEqual(stages["design"]["components"]["engine"]["status"], "n/a")
        self.assertEqual(stages["design"]["components"]["viewer"], {"status": "n/a", "record": None, "actor": None,
                                                                    "criteria": [], "prototypes": [], "sessions": []})
        for name in ("plan", "implement", "verify", "integrate", "release"):
            self.assertEqual(stages[name]["components"]["engine"]["status"], "pending", name)
            self.assertNotIn("hook", stages[name]["components"]["engine"], "undeclared hooks are not listed")
        self.assertEqual(stages["review"]["components"]["engine"]["enabled"], True)

    def test_approval_shows_actor_criteria_and_flow(self):
        decision = self.approve()
        self.plan()
        data = self.inspect()
        approve = self.stages(data)["approve"]["change"]
        self.assertEqual((approve["status"], approve["record"], approve["actor"], approve["flow"]),
                         ("done", decision["id"], "Owner", decision["flow"]))
        self.assertEqual(approve["criteria"], [{"id": "CR-002", "status": "met"}, {"id": "CR-003", "status": "met"}])
        self.assertEqual(data["flow"]["approved_under"], decision["flow"])
        plan = self.stages(data)["plan"]["components"]["engine"]
        self.assertEqual((plan["status"], plan["record"]), ("done", "engine/v0.1.0"))
        self.assertEqual(plan["releases"], [{"version": "v0.1.0", "status": "planning",
                                             "intent_revision": self.record["proposal_digest"]}])
        # Editing the flow after approval: the approval keeps the flow it was given under, unagreed now.
        path = self.root / FLOW
        path.write_text(path.read_text().replace("Approve the exact intent", "Approve the full intent"))
        flow = self.inspect()["flow"]
        self.assertEqual(flow["approved_under"], decision["flow"])
        self.assertNotEqual(flow["sha256"], decision["flow"])
        self.assertFalse(flow["agreed"])
        self.assertEqual({i["code"] for i in flow["agreement_issues"]}, {"FOUNDATION_INCOMPLETE"})

    def test_declared_pending_hook_shows_its_decider_and_criteria(self):
        self.approve()
        self.plan()
        declare_hook(self.root, "pre-implement", declared={"CR-005": "The plan is ready to implement."})
        self.call("foundation", "agree", "--ref", "flow", *ACTOR, *criteria(self.root, "foundation"))
        stages = self.stages()
        self.assertEqual(stages["implement"]["checkpoint"], {"decider": "owner", "criteria": ["CR-005"],
                                                             "on_reject": "revise", "hook": "pre-implement"})
        hook = stages["implement"]["components"]["engine"]["hook"]
        self.assertEqual(hook, {"status": "pending", "record": None, "actor": None, "criteria": [],
                                "name": "pre-implement", "subject": self.record["proposal_digest"],
                                "pending": {"decider": "owner", "criteria": [
                                    {"id": "CR-005", "text": "The plan is ready to implement."}]}})
        corrections = self.workspace / "corrections.json"
        put_json(corrections, [{"id": "R-1", "description": "Clarify the scope"}])
        base = ("checkpoint", "CHG-001", "--hook", "pre-implement", "--digest", self.record["proposal_digest"], *ACTOR)
        rejected = self.call(*base, "--component", "viewer", "--outcome", "rejected", "--corrections", corrections,
                             *criteria(self.root, "pre-implement", "rejected"))["data"]["decision"]
        approved = self.call(*base, "--component", "engine", "--outcome", "approved",
                             *criteria(self.root, "pre-implement"))["data"]["decision"]
        stages = self.stages()
        viewer = stages["implement"]["components"]["viewer"]["hook"]
        self.assertEqual((viewer["status"], viewer["record"], viewer["actor"], viewer["consequence"]),
                         ("blocked", rejected["id"], "Owner", "revise"))
        self.assertEqual(viewer["criteria"], rejected["criteria"])
        engine = stages["implement"]["components"]["engine"]["hook"]
        self.assertEqual((engine["status"], engine["record"], engine["actor"], engine["criteria"]),
                         ("done", approved["id"], "Owner", [{"id": "CR-005", "status": "met"}]))
        self.assertNotIn("pending", engine)
        self.call("change", "start", "CHG-001", "--component", "engine", "--actor", "Implementer")
        start = self.stages()["implement"]["components"]["engine"]
        self.assertEqual((start["status"], start["actor"]), ("done", "Implementer"))
        self.assertEqual(start["record"], start["start"])

    def test_rejected_change_and_canceled_components_are_blocked(self):
        corrections = self.workspace / "corrections.json"
        put_json(corrections, [{"id": "R-1", "description": "Clarify the scope"}])
        rejection = self.call("reject", "change", "CHG-001", "--digest", self.record["proposal_digest"], *ACTOR,
                              "--corrections", corrections, *criteria(self.root, "approve", "rejected"))["data"]["decision"]
        approve = self.stages()["approve"]["change"]
        self.assertEqual((approve["status"], approve["record"], approve["consequence"]), ("blocked", rejection["id"], "revise"))
        self.assertEqual(approve["criteria"], rejection["criteria"])
        self.call("change", "cancel", "CHG-001", *ACTOR)
        stages = self.stages()
        self.assertEqual(stages["approve"]["change"]["status"], "blocked")
        plan = stages["plan"]["components"]["engine"]
        self.assertEqual(plan["status"], "blocked")
        self.assertIn("canceled", plan)
        # What a canceled component still awaited is no longer presented to the decider.
        viewer = stages["foundation"]["components"]["viewer"]
        self.assertEqual(viewer["status"], "blocked")
        self.assertNotIn("pending", viewer)

    def test_prototype_checkpoint_drives_the_design_stage(self):
        self.project("prototype-project", prototype="mockups/screen.html")
        prototype = self.root / "mockups/screen.html"

        def design():
            return self.stages()["design"]["components"]

        pending = design()
        self.assertEqual(pending["engine"]["status"], "n/a", "not user-facing")
        self.assertEqual(pending["viewer"]["status"], "pending")
        self.assertEqual(pending["viewer"]["pending"]["criteria"], [{"id": "CR-004", "text": "The prototype matches the approved intention."}])
        self.assertEqual(pending["viewer"]["prototypes"][0]["state"], "draft")
        decision = self.call("checkpoint", "mockups/screen.html", "--digest", file_hash(prototype.read_bytes()), *ACTOR,
                             "--outcome", "approved", *criteria(self.root, "design"))["data"]["decision"]
        done = design()["viewer"]
        self.assertEqual((done["status"], done["record"], done["actor"], done["criteria"]),
                         ("done", decision["id"], "Owner", [{"id": "CR-004", "status": "met"}]))
        prototype.write_text("<h1>Edited screen</h1>\n")
        changed = design()["viewer"]
        self.assertEqual((changed["status"], changed["prototypes"][0]["state"]), ("pending", "changed"))

    def test_missing_or_invalid_flow_keeps_inspect_working(self):
        self.approve()
        with_flow = self.inspect()
        path = self.root / FLOW
        original = path.read_bytes()
        path.unlink()
        missing = self.inspect()
        self.assertEqual(missing["flow"]["error"]["code"], "FLOW_MISSING")
        self.assertEqual(set(missing["flow"]), {"error"})
        # The skills brief is flow-derived too (TK.6): null without a flow, nothing else differs.
        self.assertIsNone(missing["skills"])
        self.assertEqual({k: v for k, v in missing.items() if k not in {"flow", "skills"}},
                         {k: v for k, v in with_flow.items() if k not in {"flow", "skills"}},
                         "only the flow-derived sections differ")
        path.write_bytes(b"schema = [")
        self.assertEqual(self.inspect()["flow"]["error"]["code"], "FLOW_INVALID")
        path.write_bytes(original)
        self.assertNotIn("error", self.inspect()["flow"])
        # list changes skips the section; the listing is unchanged.
        listed = self.call("list", "changes")["data"]
        self.assertNotIn("flow", json.dumps(listed))

    def test_inspect_is_deterministic_and_human_output_is_a_table(self):
        self.approve()
        self.plan()
        first = invoke(["--project", str(self.root), "--json", "inspect", "--change", "CHG-001"]).stdout
        second = invoke(["--project", str(self.root), "--json", "inspect", "--change", "CHG-001"]).stdout
        self.assertEqual(json.loads(first)["data"]["flow"], json.loads(second)["data"]["flow"])
        human = invoke(["--project", str(self.root), "inspect", "--change", "CHG-001"])
        self.assertEqual(human.returncode, 0, human.stdout)
        self.assertIn("Stage       AI   Component  Status", human.stdout)
        self.assertIn("approve     no   —          done", human.stdout)
        self.assertIn("Note — approve: Roclec records the actor declared", human.stdout)


if __name__ == "__main__":
    unittest.main()
