"""Project flow as a kernel authority: seeding, process reference, approval pin and views (TF.2, TF.3, TF.6)."""
from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from roclec_spec_kit import flow
from roclec_spec_kit.config import load_profile
from roclec_spec_kit.model import ModelError, sha
from roclec_spec_kit.store import Store
from scripts.c1_scenarios import bundle, criteria, digest, foundation, init_trunk, profile, put_json, tree
try:
    from test_kernel import invoke
except ModuleNotFoundError:  # run as tests.test_flow_kernel
    from tests.test_kernel import invoke

DEFAULT = files("roclec_spec_kit").joinpath("assets/project/flow.toml").read_bytes()
FLOW = ".roclec/flow.toml"
BOTH = ("--component", "engine", "--component", "viewer")
ACTOR = ("--actor", "Maintainer", "--reason", "Reviewed")


def flow_codes(payload):
    return [i["code"] for i in payload["issues"] if i["code"].startswith("FLOW_")]


class FlowKernelTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)
        self.root = self.workspace / "project"
        self.config = self.workspace / "profile.toml"
        profile(self.config)

    def init(self, root=None, expect=0, issue=None):
        root = root or self.root
        if not (root / ".git").exists():
            init_trunk(root)
        before = tree(root)
        result = invoke(["--json", "init", str(root), "--profile", str(self.config)])
        self.assertEqual(result.returncode, expect, result.stdout)
        if issue:
            self.assertIn(issue, [i["code"] for i in json.loads(result.stdout)["issues"]], result.stdout)
            self.assertEqual(tree(root), before, "Rejected init mutated the project")
        return json.loads(result.stdout)

    def call(self, *args, expect=0, issue=None):
        before = tree(self.root)
        result = invoke(["--project", str(self.root), "--json", *args])
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        if issue:
            self.assertIn(issue, [i["code"] for i in payload["issues"]], result.stdout)
        if expect in (1, 2, 3):
            self.assertEqual(tree(self.root), before, "Rejected operation mutated consumer")
        return payload

    def write_flow(self, mutate=None, raw=None):
        data = raw if raw is not None else DEFAULT.decode()
        if mutate:
            data = mutate(data)
        (self.root / FLOW).write_text(data, encoding="utf-8")
        return (self.root / FLOW).read_bytes()

    def edit_description(self, text="Approve the exact intent of the change after a second reading."):
        return self.write_flow(lambda d: d.replace("Approve the exact intent of the change; approval freezes its digest.", text))

    def approved_change(self):
        folder = self.workspace / "draft"
        record = bundle(folder)
        self.call("change", "new", "--file", str(folder / "change.json"))
        approval = self.call("change", "approve", "CHG-001", "--digest", record["proposal_digest"], *ACTOR,
                             *criteria(self.root, "approve"))["data"]
        return record, approval["decision"]

    # TF.2 — seeding

    def test_init_seeds_valid_flow_and_current_view(self):
        self.init()
        self.assertEqual((self.root / FLOW).read_bytes(), DEFAULT)
        parsed = flow.load(self.root)
        view = (self.root / "docs/flow.md").read_bytes()
        self.assertEqual(flow.view_status(parsed, load_profile(self.root).data, view), "current")
        checked = self.call("check")
        self.assertEqual(flow_codes(checked), [], checked)
        self.assertEqual(self.call("views")["data"]["written"], [])

    def test_init_keeps_consumer_flow_and_view(self):
        self.root.mkdir()
        (self.root / ".roclec").mkdir()
        own = DEFAULT.replace(b'view = "docs/flow.md"', b'view = "docs/process.md"')
        (self.root / FLOW).write_bytes(own)
        (self.root / "docs").mkdir()
        (self.root / "docs/process.md").write_text("# Our process notes\n")
        self.init()
        self.assertEqual((self.root / FLOW).read_bytes(), own)
        self.assertEqual((self.root / "docs/process.md").read_text(), "# Our process notes\n")
        self.assertFalse((self.root / "docs/flow.md").exists())
        self.assertEqual(flow_codes(self.call("check")), ["FLOW_VIEW_EDITED"])
        self.call("views", "--write", expect=1, issue="UNMANAGED_FILE")

    def test_init_rejects_invalid_consumer_flow_without_writes(self):
        self.root.mkdir()
        (self.root / ".roclec").mkdir()
        (self.root / FLOW).write_text("schema = 2\n")
        self.init(expect=2, issue="FLOW_INVALID")
        self.assertFalse((self.root / ".roclec/project.toml").exists())

    def test_refresh_seeds_missing_flow_and_preserves_edited_flow(self):
        self.init()
        (self.root / FLOW).unlink()
        self.call("skills")
        self.assertEqual((self.root / FLOW).read_bytes(), DEFAULT)
        flow.load(self.root)
        manifest = json.loads((self.root / ".roclec/installation.json").read_text())
        self.assertNotIn(FLOW, manifest["managed"])
        edited = self.edit_description()
        self.call("skills")
        self.assertEqual((self.root / FLOW).read_bytes(), edited, "refresh must preserve the consumer flow")
        self.call("skills")
        self.assertEqual((self.root / FLOW).read_bytes(), edited)

    # TF.6 — check and views

    def test_check_reports_stale_and_edited_views_and_views_regenerates(self):
        self.init()
        self.edit_description()
        stale = self.call("check")
        self.assertEqual(flow_codes(stale), ["FLOW_VIEW_STALE"])
        warning = next(i for i in stale["issues"] if i["code"] == "FLOW_VIEW_STALE")
        self.assertEqual((warning["severity"], warning["path"]), ("warning", "docs/flow.md"))
        self.assertIn("views --write", warning["remediation"])
        self.call("views", expect=1, issue="VIEW_STALE")
        self.assertEqual(self.call("views", "--write")["data"]["written"], ["docs/flow.md"])
        self.assertIn(b"after a second reading", (self.root / "docs/flow.md").read_bytes())
        self.assertEqual(flow_codes(self.call("check")), [])
        self.assertEqual(self.call("views")["data"]["written"], [])
        (self.root / "docs/flow.md").unlink()
        self.assertEqual(flow_codes(self.call("check")), ["FLOW_VIEW_STALE"])
        self.call("views", "--write")
        with (self.root / "docs/flow.md").open("a") as handle:
            handle.write("Hand edit\n")
        self.assertEqual(flow_codes(self.call("check")), ["FLOW_VIEW_EDITED"])
        self.call("views", "--write", expect=1, issue="UNMANAGED_FILE")

    def test_interrupted_flow_view_write_is_journaled_and_recovers(self):
        self.init()
        self.edit_description()
        original = Store._atomic

        def interrupt_view(store, relative, content):
            if relative == "docs/flow.md":
                raise OSError("synthetic interruption")
            return original(store, relative, content)

        with mock.patch.object(Store, "_atomic", interrupt_view):
            result = invoke(["--project", str(self.root), "--json", "views", "--write"])
        self.assertEqual(result.returncode, 4, result.stdout)
        operation = json.loads(result.stdout)["issues"][0]["entity"]
        self.call("check", expect=4, issue="IO_PARTIAL")
        self.call("operation", "recover", operation)
        self.assertEqual(flow_codes(self.call("check")), [])
        with self.assertRaises(ModelError):
            Store(self.root).apply("views", {"flow_view": "AGENTS.md"}, {"AGENTS.md": b"overwrite"}, Store(self.root).token())

    def test_check_flow_missing_invalid_and_unused_criterion(self):
        self.init()
        self.write_flow(lambda d: d + '\n[criteria.CR-009]\ntext = "Spare"\n')
        self.assertEqual(flow_codes(self.call("check")), ["FLOW_CRITERION_UNUSED", "FLOW_VIEW_STALE"])
        self.write_flow(raw="schema = 1\n")
        self.call("check", expect=2, issue="FLOW_INVALID")
        self.call("views", "--write", expect=2, issue="FLOW_INVALID")
        (self.root / FLOW).unlink()
        missing = self.call("check")
        self.assertEqual(flow_codes(missing), ["FLOW_MISSING"])
        warning = missing["issues"][0]
        self.assertEqual(warning["severity"], "warning")
        self.assertIn("roclec skills", warning["remediation"])
        self.assertIn("--role process", warning["remediation"])
        self.assertEqual(self.call("views")["data"]["written"], [], "a missing flow skips its view")

    # TF.3 — process reference

    def test_process_reference_shape_is_enforced(self):
        self.init()
        other = self.root / ".roclec/other.toml"
        other.write_bytes(DEFAULT)
        self.call("reference", "add", "flow", "--path", ".roclec/other.toml", "--role", "process", *BOTH,
                  expect=1, issue="INVALID_REFERENCE")
        partial = self.call("reference", "add", "flow", "--path", FLOW, "--role", "process", "--component", "engine",
                            expect=1, issue="INVALID_REFERENCE")
        self.assertIn("--component viewer", partial["issues"][0]["remediation"])
        self.call("reference", "add", "flow", "--path", FLOW, "--role", "process", *BOTH)
        self.call("reference", "add", "flow-two", "--path", FLOW, "--role", "process", *BOTH,
                  expect=1, issue="INVALID_REFERENCE")
        self.call("reference", "update", "flow", "--path", FLOW, "--role", "process", "--component", "viewer",
                  expect=1, issue="INVALID_REFERENCE")
        self.write_flow(raw="schema = 1\n")
        self.call("reference", "update", "flow", "--path", FLOW, "--role", "process", *BOTH, expect=2, issue="FLOW_INVALID")
        self.call("foundation", "agree", "--ref", "flow", *ACTOR, expect=2, issue="FLOW_INVALID")

    def test_process_is_required_and_invalid_agreed_flow_is_reported(self):
        self.init()
        foundation(self.root)
        references = json.loads((self.root / ".roclec/references.json").read_text())
        references["references"] = [r for r in references["references"] if r["role"] != "process"]
        put_json(self.root / ".roclec/references.json", references)
        missing = self.call("foundation", "check", "--component", "viewer", expect=1, issue="FOUNDATION_INCOMPLETE")
        self.assertEqual([i["message"] for i in missing["issues"]], ["Missing agreed process reference"])
        self.assertIn("--role process", missing["issues"][0]["remediation"])
        bound = self.root / ".claude/agents/bot.md"
        bound.parent.mkdir(parents=True)
        bound.write_text("Synthetic consumer agent\n")
        self.write_flow(lambda d: d + '\n[roles.bot]\nkind = "agent"\n')
        self.call("reference", "add", "flow", "--path", FLOW, "--role", "process", *BOTH)
        self.call("foundation", "agree", "--ref", "flow", *ACTOR, *criteria(self.root, "foundation"))
        self.call("foundation", "check", "--component", "engine")
        bound.unlink()
        invalid = self.call("foundation", "check", "--component", "engine", expect=1, issue="FLOW_INVALID")
        self.assertEqual([i["code"] for i in invalid["issues"]], ["FLOW_INVALID"])

    # TF.3 — approval pin and implement gate

    def test_approval_requires_a_valid_flow_and_pins_its_bytes(self):
        self.init()
        folder = self.workspace / "draft"
        record = bundle(folder)
        self.call("change", "new", "--file", str(folder / "change.json"))
        (self.root / FLOW).unlink()
        self.call("check", "--change", "CHG-001", "--gate", "approve", expect=2, issue="FLOW_MISSING")
        self.call("change", "approve", "CHG-001", "--digest", record["proposal_digest"], *ACTOR, expect=2, issue="FLOW_MISSING")
        self.write_flow(raw="schema = 1\n")
        self.call("change", "approve", "CHG-001", "--digest", record["proposal_digest"], *ACTOR, expect=2, issue="FLOW_INVALID")
        raw = self.edit_description()
        self.call("check", "--change", "CHG-001", "--gate", "approve")
        # Approval needs a valid flow, not its agreement (enforced at implement).
        decision = self.call("change", "approve", "CHG-001", "--digest", record["proposal_digest"], *ACTOR,
                             *criteria(self.root, "approve"))["data"]["decision"]
        self.assertEqual(decision["flow"], sha(raw))
        inspected = self.call("inspect", "--change", "CHG-001")["data"]
        self.assertEqual(inspected["approval"]["flow"], sha(raw))

    def test_flow_edit_after_agreement_blocks_implement_until_reagreed(self):
        self.init()
        foundation(self.root)
        self.call("foundation", "check", "--component", "engine")
        _, decision = self.approved_change()
        pinned = sha((self.root / FLOW).read_bytes())
        self.assertEqual(decision["flow"], pinned)
        self.call("release", "plan", "engine", "v0.1.0", "--change", "CHG-001")
        gate = ("check", "--change", "CHG-001", "--component", "engine", "--gate", "implement")
        self.call(*gate)
        self.edit_description()
        blocked = self.call(*gate, expect=1, issue="FOUNDATION_INCOMPLETE")
        self.assertIn("flow", json.dumps(blocked["issues"][0]["actual"]))
        self.call("change", "start", "CHG-001", "--actor", "Maintainer", "--component", "engine",
                  expect=1, issue="FOUNDATION_INCOMPLETE")
        self.call("foundation", "agree", "--ref", "flow", *ACTOR, *criteria(self.root, "foundation"))
        self.call(*gate)
        self.call("change", "start", "CHG-001", "--actor", "Maintainer", "--component", "engine")
        # The approval keeps the flow it was given under; re-agreement does not rewrite history.
        self.assertEqual(self.call("inspect", "--change", "CHG-001")["data"]["approval"]["flow"], pinned)

    def test_flow_pin_is_validated_on_decisions(self):
        self.init()
        foundation(self.root)
        _, decision = self.approved_change()
        path = self.root / f".roclec/decisions/{decision['id']}.json"
        forged = {k: v for k, v in decision.items() if k != "id"} | {"flow": "not-a-digest"}
        forged["id"] = digest(forged)
        path.unlink()
        put_json(self.root / f".roclec/decisions/{forged['id']}.json", forged)
        self.call("check", expect=2, issue="INVALID_INPUT")
        # An approval cannot record an unmet criterion, whatever today's flow declares.
        unmet = {k: v for k, v in decision.items() if k != "id"} | {"criteria": [
            {"id": "CR-002", "status": "not-met", "reason": "Forged"}, {"id": "CR-003", "status": "met"}]}
        unmet["id"] = digest(unmet)
        (self.root / f".roclec/decisions/{forged['id']}.json").unlink()
        put_json(self.root / f".roclec/decisions/{unmet['id']}.json", unmet)
        self.call("check", expect=2, issue="INVALID_INPUT")
        (self.root / f".roclec/decisions/{unmet['id']}.json").unlink()
        put_json(path, decision)
        self.call("check")
        cancellation = self.call("change", "cancel", "CHG-001", *ACTOR)["data"]["decision"]
        cancel_path = self.root / f".roclec/decisions/{cancellation['id']}.json"
        for key, value in (("flow", "0" * 64), ("criteria", [])):
            misplaced = {k: v for k, v in cancellation.items() if k != "id"} | {key: value}
            misplaced["id"] = digest(misplaced)
            cancel_path.unlink()
            put_json(self.root / f".roclec/decisions/{misplaced['id']}.json", misplaced)
            self.call("check", expect=2, issue="INVALID_INPUT")
            (self.root / f".roclec/decisions/{misplaced['id']}.json").unlink()
            put_json(cancel_path, cancellation)
        self.call("check")


if __name__ == "__main__":
    unittest.main()
