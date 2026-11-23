"""Criteria in decisions (TF.4, D28) and human checkpoints at flow hooks (TF.5)."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from roclec_spec_kit.model import sha
from roclec_spec_kit.store import Store
from scripts.c1_scenarios import (bundle, criteria, declare_hook, digest, file_hash, foundation, init_trunk, profile,
                                  put_json, tree)
from scripts.c3_scenarios import hook_scenarios
try:
    from test_kernel import invoke
except ModuleNotFoundError:  # run as tests.test_flow_decisions
    from tests.test_kernel import invoke

FLOW = ".roclec/flow.toml"
ACTOR = ("--actor", "Owner", "--reason", "Reviewed")


class FlowDecisionsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)
        self.root = self.workspace / "project"
        init_trunk(self.root)
        config = self.workspace / "profile.toml"
        profile(config)
        result = invoke(["--json", "init", str(self.root), "--profile", str(config)])
        self.assertEqual(result.returncode, 0, result.stdout)
        foundation(self.root)
        self.record = bundle(self.workspace / "draft")
        self.call("change", "new", "--file", str(self.workspace / "draft/change.json"))

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

    def evaluations(self, rows, name="evaluations"):
        path = self.workspace / f"{name}.json"
        put_json(path, rows)
        return ("--criteria", path)

    def corrections(self):
        path = self.workspace / "corrections.json"
        put_json(path, [{"id": "R-1", "description": "Clarify the scope"}])
        return ("--corrections", path)

    def flow_sha(self):
        return sha((self.root / FLOW).read_bytes())

    def approve(self, digest_=None, **kwargs):
        return self.call("change", "approve", "CHG-001", "--digest", digest_ or self.record["proposal_digest"], *ACTOR,
                         *criteria(self.root, "approve"), **kwargs)

    def plan(self):
        self.call("release", "plan", "engine", "v0.1.0", "--change", "CHG-001")
        self.call("release", "plan", "viewer", "v0.1.0", "--change", "CHG-001")

    def agree_flow(self):
        self.call("foundation", "agree", "--ref", "flow", *ACTOR, *criteria(self.root, "foundation"))

    def hook(self, *args, component="engine", digest_=None, expect=0, issue=None):
        return self.call("checkpoint", "CHG-001", "--hook", "pre-implement", "--component", component,
                         "--digest", digest_ or self.current()["proposal_digest"], *ACTOR, *args, expect=expect, issue=issue)

    def current(self):
        return json.loads((self.root / ".roclec/changes/CHG-001/change.json").read_text())

    def gate(self, component="engine", **kwargs):
        return self.call("check", "--change", "CHG-001", "--component", component, "--gate", "implement", **kwargs)

    def revise(self, note):
        """Edit the stored proposal in place, as a revision after a rejected checkpoint."""
        folder = self.root / ".roclec/changes/CHG-001"
        record = self.current()
        proposal = folder / "proposal.md"
        proposal.write_text(proposal.read_text() + note)
        record["semantic"]["files"]["proposal.md"] = file_hash(proposal.read_bytes())
        record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
        put_json(folder / "change.json", record)
        return record["proposal_digest"]

    # TF.4 — criteria in approve, agree, checkpoint and reject

    def test_approval_criteria_rules(self):
        proposal = ("change", "approve", "CHG-001", "--digest", self.record["proposal_digest"], *ACTOR)
        met = [{"id": "CR-002", "status": "met"}, {"id": "CR-003", "status": "n/a", "reason": "No behavior change"}]
        self.call(*proposal, expect=2, issue="CRITERIA_MISMATCH")
        self.call(*proposal, *self.evaluations(met[:1]), expect=2, issue="CRITERIA_MISMATCH")
        self.call(*proposal, *self.evaluations(met + [{"id": "CR-004", "status": "met"}]), expect=2, issue="CRITERIA_MISMATCH")
        self.call(*proposal, *self.evaluations([met[0], {"id": "CR-003", "status": "n/a"}]),
                  expect=2, issue="CRITERIA_REASON_REQUIRED")
        self.call(*proposal, *self.evaluations([met[0], {"id": "CR-003", "status": "not-met", "reason": "Vague"}]),
                  expect=2, issue="CRITERIA_NOT_MET")
        self.call(*proposal, *self.evaluations({"CR-002": "met"}), expect=2, issue="INVALID_INPUT")
        decision = self.call(*proposal, *self.evaluations(list(reversed(met))))["data"]["decision"]
        self.assertEqual(decision["criteria"], met, "criteria are stored normalized and sorted")
        self.assertEqual(decision["flow"], self.flow_sha())

        refs = ("foundation", "agree", "--ref", "architecture", *ACTOR)
        self.call(*refs, *self.evaluations([{"id": "CR-001", "status": "not-met", "reason": "x"}]),
                  expect=2, issue="CRITERIA_NOT_MET")
        self.call(*refs, expect=2, issue="CRITERIA_MISMATCH")
        agreed = self.call(*refs, *criteria(self.root, "foundation"))["data"]["decision"]
        self.assertEqual((agreed["criteria"], agreed["flow"]), ([{"id": "CR-001", "status": "met"}], self.flow_sha()))
        self.call("foundation", "check", "--component", "engine")

        prototype = self.root / "mockups/screen.html"
        prototype.parent.mkdir()
        prototype.write_text("<h1>Screen</h1>\n")
        shot = ("checkpoint", "mockups/screen.html", "--digest", file_hash(prototype.read_bytes()), *ACTOR, "--outcome", "approved")
        self.call(*shot, expect=2, issue="CRITERIA_MISMATCH")
        self.call(*shot, "--component", "engine", *criteria(self.root, "design"), expect=2, issue="INVALID_INPUT")
        visual = self.call(*shot, *criteria(self.root, "design"))["data"]["decision"]
        self.assertEqual((visual["criteria"], visual["flow"]), ([{"id": "CR-004", "status": "met"}], self.flow_sha()))
        self.call("check")

    def test_rejection_criteria_and_default_consequence(self):
        reject = ("reject", "change", "CHG-001", "--digest", self.record["proposal_digest"], *ACTOR)
        self.call(*reject, *self.corrections(), *criteria(self.root, "approve"), expect=2, issue="CRITERIA_REQUIRED")
        self.call(*reject, *self.corrections(), expect=2, issue="CRITERIA_MISMATCH")
        # No --consequence: the approve point declares on_reject = "revise", which needs corrections.
        self.call(*reject, *criteria(self.root, "approve", "rejected"), expect=2, issue="INVALID_INPUT")
        decision = self.call(*reject, *self.corrections(), *criteria(self.root, "approve", "rejected"))["data"]["decision"]
        self.assertEqual(decision["consequence"], "revise")
        self.assertEqual(decision["flow"], self.flow_sha())
        self.assertEqual([r["status"] for r in decision["criteria"]], ["not-met", "met"])

        # A point that declares no criteria accepts an empty rejection; on_reject = defer needs a FUT.
        text = (self.root / FLOW).read_text()
        (self.root / FLOW).write_text(text.replace(
            'checkpoint = { decider = "owner", criteria = ["CR-001"], on_reject = "revise" }',
            'checkpoint = { decider = "owner", criteria = [], on_reject = "defer" }'))
        reference = file_hash((self.root / "docs/reference.md").read_bytes())
        refuse = ("reject", "reference", "context", "--digest", reference, *ACTOR, *self.corrections())
        self.call(*refuse, expect=2, issue="INVALID_INPUT")
        self.call(*refuse, "--fut", "FUT-001", *self.evaluations([{"id": "CR-001", "status": "not-met", "reason": "x"}]),
                  expect=1, issue="INVALID_REFERENCE")
        fut = self.workspace / "fut.json"
        put_json(fut, {"model_schema": 2, "id": "FUT-001", "source": {"location": "docs/reference.md", "locator": "Context"},
                       "finding": "Later", "impact": "Fixture", "questions": []})
        self.call("fut", "capture", "--file", fut)
        self.call(*refuse, "--fut", "FUT-001", *self.evaluations([{"id": "CR-001", "status": "not-met", "reason": "x"}]),
                  expect=2, issue="CRITERIA_MISMATCH")
        deferred = self.call(*refuse, "--fut", "FUT-001")["data"]["decision"]
        self.assertEqual((deferred["consequence"], deferred["criteria"], deferred["flow"]), ("defer", [], self.flow_sha()))
        self.call("check")

    def test_historical_decisions_stay_valid_without_reevaluation(self):
        self.approve()
        self.plan()
        approval = next(json.loads(p.read_text()) for p in (self.root / ".roclec/decisions").glob("*.json")
                        if json.loads(p.read_text())["kind"] == "change-approve")
        # A pre-FF approval carries neither criteria nor a flow pin.
        historical = {k: v for k, v in approval.items() if k not in {"id", "criteria", "flow"}}
        historical["id"] = digest(historical)
        (self.root / f".roclec/decisions/{approval['id']}.json").unlink()
        put_json(self.root / f".roclec/decisions/{historical['id']}.json", historical)
        self.call("check")
        self.gate()
        # Declaring a new approve criterion later does not invalidate the recorded evaluation.
        text = (self.root / FLOW).read_text().replace('criteria = ["CR-002", "CR-003"]', 'criteria = ["CR-002", "CR-003", "CR-009"]')
        (self.root / FLOW).write_text(text + '\n[criteria.CR-009]\ntext = "New criterion"\n')
        self.agree_flow()
        self.call("check")
        self.gate()

    # TF.5 — hooks

    def test_undeclared_hooks_block_nothing(self):
        self.approve()
        self.plan()
        self.gate()
        self.hook("--outcome", "approved", expect=1, issue="INVALID_REFERENCE")
        self.call("change", "start", "CHG-001", "--component", "engine", "--actor", "Owner")

    def test_pre_implement_revise_cycle_and_independent_chains(self):
        self.approve()
        self.plan()
        declare_hook(self.root, "pre-implement", declared={"CR-005": "The plan is ready to implement."})
        self.agree_flow()
        first = self.record["proposal_digest"]
        blocked = self.gate(expect=1, issue="CHECKPOINT_REQUIRED")["issues"][0]
        self.assertEqual((blocked["entity"], blocked["expected"], blocked["actual"]), ("CHG-001/engine/pre-implement", first, None))
        self.assertIn(f"roclec checkpoint CHG-001 --hook pre-implement --component engine --digest {first} --outcome approved",
                      blocked["remediation"])
        self.assertIn("CR-005", blocked["remediation"])
        self.call("change", "start", "CHG-001", "--component", "engine", "--actor", "Owner", expect=1, issue="CHECKPOINT_REQUIRED")
        self.hook("--outcome", "approved", *criteria(self.root, "pre-implement"), digest_="0" * 64, expect=1, issue="APPROVAL_STALE")
        self.hook("--outcome", "approved", expect=2, issue="CRITERIA_MISMATCH")
        self.hook("--outcome", "approved", *criteria(self.root, "pre-implement", "rejected"), expect=2, issue="CRITERIA_NOT_MET")
        self.hook("--outcome", "rejected", *self.corrections(), *criteria(self.root, "pre-implement"), expect=2, issue="CRITERIA_REQUIRED")
        self.hook("--outcome", "approved", "--consequence", "revise", *criteria(self.root, "pre-implement"), expect=2, issue="INVALID_INPUT")
        rejected = self.hook("--outcome", "rejected", *self.corrections(),
                             *criteria(self.root, "pre-implement", "rejected"))["data"]["decision"]
        self.assertEqual((rejected["kind"], rejected["consequence"], rejected["hook"], rejected["component"]),
                         ("checkpoint", "revise", "pre-implement", "engine"))
        self.assertNotIn("files", rejected, "stage subjects are immutable records; nothing is frozen")
        self.assertEqual(self.gate(expect=1, issue="CHECKPOINT_REQUIRED")["issues"][0]["actual"], "rejected")
        self.hook("--outcome", "approved", *criteria(self.root, "pre-implement"), expect=1, issue="REJECTION_UNRESOLVED")
        opened = self.call("list", "rejections", "--open")["data"]["rejections"]
        self.assertEqual([row["id"] for row in opened], [rejected["id"]])
        # Hooks are per component: viewer is still undecided, engine was rejected.
        self.gate("viewer", expect=1, issue="CHECKPOINT_REQUIRED")
        # A trunk change decision between hook decisions does not fork their chains.
        self.call("review", "policy", "--change", "CHG-001", "--enabled", "false", *ACTOR)
        viewer = self.hook("--outcome", "approved", *criteria(self.root, "pre-implement"), component="viewer")["data"]["decision"]
        self.assertIsNone(viewer["previous"], "each component's hooks start their own chain")
        self.gate("viewer")

        second = self.revise("Clarify the scope as requested.\n")
        self.approve(second)
        self.plan()
        self.gate(expect=1, issue="CHECKPOINT_REQUIRED")
        self.hook("--outcome", "approved", *criteria(self.root, "pre-implement"), expect=1, issue="CORRECTIONS_REQUIRED")
        addresses = self.workspace / "addresses.json"
        put_json(addresses, {"rejection": rejected["id"], "corrections": [{"id": "R-2", "status": "addressed"}]})
        self.hook("--outcome", "approved", "--addresses", addresses, *criteria(self.root, "pre-implement"),
                  expect=1, issue="CORRECTIONS_REQUIRED")
        put_json(addresses, {"rejection": rejected["id"], "corrections": [{"id": "R-1", "status": "addressed"}]})
        approved = self.hook("--outcome", "approved", "--addresses", addresses, *criteria(self.root, "pre-implement"))["data"]["decision"]
        self.assertEqual(approved["previous"], rejected["id"])
        self.gate()
        self.gate("viewer", expect=1, issue="CHECKPOINT_REQUIRED")
        self.assertEqual(self.call("list", "rejections", "--open")["data"]["rejections"], [])
        history = self.call("list", "rejections")["data"]["rejections"]
        self.assertEqual([(row["id"], row["revision"]["decision"]) for row in history], [(rejected["id"], approved["id"])])
        self.call("change", "start", "CHG-001", "--component", "engine", "--actor", "Owner")
        self.call("check")

    def test_older_approval_cannot_bypass_a_later_revise_rejection(self):
        """Codex review: approve A, reject B (revise), restore A's bytes; A's old approval must not count."""
        self.approve()
        self.plan()
        declare_hook(self.root, "pre-implement")
        self.agree_flow()
        folder = self.root / ".roclec/changes/CHG-001"
        original = {name: (folder / name).read_bytes() for name in ("change.json", "proposal.md")}
        first = self.record["proposal_digest"]
        self.hook("--outcome", "approved")
        self.gate()
        second = self.revise("A different scope.\n")
        self.approve(second)
        self.plan()
        rejected = self.hook("--outcome", "rejected", *self.corrections())["data"]["decision"]
        for name, data in original.items():
            (folder / name).write_bytes(data)
        self.approve(first)
        self.plan()
        blocked = self.gate(expect=1, issue="CHECKPOINT_REQUIRED")["issues"][0]
        self.assertEqual((blocked["expected"], blocked["actual"]), (first, "approved"))
        self.call("change", "start", "CHG-001", "--component", "engine", "--actor", "Owner", expect=1, issue="CHECKPOINT_REQUIRED")
        self.hook("--outcome", "approved", expect=1, issue="CORRECTIONS_REQUIRED")
        addresses = self.workspace / "addresses.json"
        put_json(addresses, {"rejection": rejected["id"], "corrections": [{"id": "R-1", "status": "disputed",
                                                                           "reason": "The original scope stands"}]})
        self.hook("--outcome", "approved", "--addresses", addresses)
        self.gate()
        self.call("check")

    def test_paired_prototype_checkpoint_repeats_the_rejection_evaluation(self):
        prototype = self.root / "mockups/screen.html"
        prototype.parent.mkdir()
        prototype.write_text("<h1>Screen</h1>\n")
        result = self.call("checkpoint", "mockups/screen.html", "--digest", file_hash(prototype.read_bytes()), *ACTOR,
                           "--outcome", "rejected", *self.corrections(), *criteria(self.root, "design", "rejected"))["data"]
        rejection, paired = result["decision"], result["checkpoint"]
        self.assertEqual((paired["criteria"], paired["flow"]), (rejection["criteria"], rejection["flow"]))
        self.assertEqual(paired["criteria"], [{"id": "CR-004", "status": "not-met", "reason": "Synthetic reviewer found it unmet"}])
        self.call("check")
        path = self.root / f".roclec/decisions/{paired['id']}.json"
        for change, code in (({"flow": "0" * 64}, "INVALID_REFERENCE"),
                             ({"criteria": [{"id": "CR-009", "status": "not-met", "reason": "x"}]}, "INVALID_REFERENCE"),
                             ({"criteria": [{"id": "CR-004", "status": "met"}]}, "INVALID_INPUT")):
            forged = {k: v for k, v in paired.items() if k != "id"} | change
            forged["id"] = digest(forged)
            path.unlink()
            put_json(self.root / f".roclec/decisions/{forged['id']}.json", forged)
            self.call("check", expect=1 if code == "INVALID_REFERENCE" else 2, issue=code)
            (self.root / f".roclec/decisions/{forged['id']}.json").unlink()
            put_json(path, paired)
        # A paired checkpoint recorded before FF, without the evaluation, stays valid.
        historical = {k: v for k, v in paired.items() if k not in {"id", "criteria", "flow"}}
        historical["id"] = digest(historical)
        path.unlink()
        put_json(self.root / f".roclec/decisions/{historical['id']}.json", historical)
        self.call("check")

    def test_pre_implement_cancel_pairs_change_cancel_and_defer_needs_fut(self):
        self.approve()
        self.plan()
        declare_hook(self.root, "pre-implement", on_reject="cancel")
        self.agree_flow()
        self.hook("--outcome", "rejected", "--consequence", "defer", expect=2, issue="INVALID_INPUT")
        self.hook("--outcome", "rejected", "--fut", "FUT-001", expect=2, issue="INVALID_INPUT")
        result = self.hook("--outcome", "rejected")["data"]
        decision, cancellation = result["decision"], result["cancellation"]
        self.assertEqual((decision["consequence"], decision["corrections"], decision["criteria"]), ("cancel", [], []))
        self.assertEqual((cancellation["kind"], cancellation["components"]), ("change-cancel", ["engine"]))
        self.assertEqual(sorted(result["receipt"]["writes"]),
                         sorted([f".roclec/decisions/{decision['id']}.json", f".roclec/decisions/{cancellation['id']}.json"]))
        self.gate(expect=1, issue="CHANGE_CANCELED")
        self.hook("--outcome", "approved", expect=1, issue="CHANGE_CANCELED")
        self.gate("viewer", expect=1, issue="CHECKPOINT_REQUIRED")
        self.call("check")
        # The pair is structural: a canceling stage rejection without its cancellation fails check.
        path = self.root / f".roclec/decisions/{cancellation['id']}.json"
        path.unlink()
        self.call("check", expect=1, issue="INVALID_REFERENCE")
        put_json(path, cancellation)

        fut = self.workspace / "fut.json"
        put_json(fut, {"model_schema": 2, "id": "FUT-001", "source": {"location": "docs/reference.md", "locator": "Context"},
                       "finding": "Later", "impact": "Fixture", "questions": []})
        self.call("fut", "capture", "--file", fut)
        deferred = self.hook("--outcome", "rejected", "--consequence", "defer", *self.corrections(), "--fut", "FUT-001",
                             component="viewer")["data"]["decision"]
        self.assertEqual((deferred["consequence"], deferred["fut"]), ("defer", "FUT-001"))
        self.gate("viewer", expect=1, issue="CHECKPOINT_REQUIRED")
        # Defer does not require a new revision: the same proposal can be approved later.
        self.hook("--outcome", "approved", component="viewer")
        self.gate("viewer")
        self.call("check")

    def test_interrupted_stage_cancel_recovers_both_records(self):
        self.approve()
        self.plan()
        declare_hook(self.root, "pre-implement", on_reject="cancel")
        self.agree_flow()
        original = Store._atomic
        writes = []

        def interrupted(store, relative, content):
            if relative.startswith(".roclec/decisions/"):
                writes.append(relative)
                if len(writes) == 2:
                    raise OSError("synthetic interruption")
            return original(store, relative, content)

        with mock.patch.object(Store, "_atomic", interrupted):
            result = invoke(["--project", str(self.root), "--json", "checkpoint", "CHG-001", "--hook", "pre-implement",
                             "--component", "engine", "--digest", self.record["proposal_digest"], *ACTOR, "--outcome", "rejected"])
        self.assertEqual(result.returncode, 4, result.stdout)
        operation = json.loads(result.stdout)["data"]["operation_id"]
        self.call("check", expect=4, issue="IO_PARTIAL")
        self.call("operation", "recover", operation)
        kinds = [d["kind"] for d in self.call("inspect", "--change", "CHG-001")["data"]["decisions"]]
        self.assertIn("change-cancel", kinds)
        self.assertIn("checkpoint", kinds)
        self.gate(expect=1, issue="CHANGE_CANCELED")
        self.call("check")

    def test_forged_stage_records_fail_check(self):
        self.approve()
        self.plan()
        declare_hook(self.root, "pre-implement")
        self.agree_flow()
        approved = self.hook("--outcome", "approved")["data"]["decision"]
        path = self.root / f".roclec/decisions/{approved['id']}.json"
        cases = [({"consequence": "revise", "corrections": []}, "INVALID_INPUT"),
                 ({"criteria": [{"id": "CR-001", "status": "not-met", "reason": "x"}]}, "INVALID_INPUT"),
                 ({"run": "RUN-x"}, "INVALID_INPUT"),
                 ({"hook": "pre-merge"}, "INVALID_INPUT"),
                 ({"component": "ghost"}, "INVALID_REFERENCE"),
                 ({"subject": {"type": "stage", "entity": "CHG-002", "digest": approved["subject"]["digest"]}}, "INVALID_INPUT")]
        for change, code in cases:
            forged = {k: v for k, v in approved.items() if k != "id"} | change
            forged["id"] = digest(forged)
            path.unlink()
            put_json(self.root / f".roclec/decisions/{forged['id']}.json", forged)
            self.call("check", expect=1 if code == "INVALID_REFERENCE" else 2, issue=code)
            (self.root / f".roclec/decisions/{forged['id']}.json").unlink()
            put_json(path, approved)
        self.call("check")
        # An approval after a revise rejection of the same digest is structurally unresolved.
        path.unlink()
        rejected = self.hook("--outcome", "rejected", *self.corrections())["data"]["decision"]
        forged = {k: v for k, v in approved.items() if k != "id"} | {"previous": rejected["id"]}
        forged["id"] = digest(forged)
        put_json(self.root / f".roclec/decisions/{forged['id']}.json", forged)
        self.call("check", expect=1, issue="REJECTION_UNRESOLVED")

    def test_hooks_with_real_runs_integration_and_release(self):
        hook_scenarios(self.workspace, invoke, lambda name, condition, detail="": self.assertTrue(condition, f"{name}: {detail}"))


if __name__ == "__main__":
    unittest.main()
