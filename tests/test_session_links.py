"""TL.3-TL.5 (M-34): records cite agent sessions, required stages demand them at their gates,
and process FUTs link a flow friction to the agreement that adjusted the flow."""
from pathlib import Path
import json
import re
import tempfile
import unittest

from scripts.c1_scenarios import FLOW, bundle, criteria, digest, put_json
from scripts.c2_scenarios import PRODUCER, commit, setup
from test_kernel import invoke
from roclec_spec_kit import flow as project_flow
from roclec_spec_kit.config import load_profile
from roclec_spec_kit.kernel import Kernel
from roclec_spec_kit.model import ModelError

TRANSCRIPT = b"user: please do the fixture work\nassistant: done\n"
MISSING = "EVD-" + "0" * 26
ROLES = {"foundation": "coordinator", "define": "specifier", "review": "reviewer", "integrate": "coordinator",
         "release": "coordinator"}
COMPONENT_STAGES = ("design", "implement", "verify", "review", "integrate")


def files(root):
    """Every file below root except Git internals, by relative path."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts}


class SessionLinksBase(unittest.TestCase):
    review = None  # Profile [review] table passed to the C2 fixture (None: review disabled).

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)
        self.root, self.base = setup(self.workspace, invoke, review=self.review)
        self.inputs = self.workspace / "inputs"
        self.inputs.mkdir()
        self.sessions = 0

    def call(self, *args, expect=0, issue=None):
        result = invoke(["--project", str(self.root), "--json", *map(str, args)])
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        if issue:
            self.assertIn(issue, [i["code"] for i in payload["issues"]], result.stdout)
        return payload

    def check_issues(self):
        """`check` issues except two expected warnings of these fixtures: the flow view's staleness (its learning
        section counts these records, TL.6) and redacted copies in a fixture profile that declares no secrets."""
        return [i for i in self.call("check")["issues"] if i["code"] not in {"FLOW_VIEW_STALE", "SESSION_REDACTION_EMPTY"}]

    def rejected(self, *args, issue, expect=2):
        """A rejected command reports `issue` and writes nothing."""
        before = files(self.root)
        payload = self.call(*args, expect=expect, issue=issue)
        self.assertEqual(files(self.root), before, args)
        return payload["issues"][0]

    def session(self, stage="implement", **overrides):
        """Import an agent session; scope defaults to CHG-001 (and engine for component stages)."""
        self.sessions += 1
        meta = {"model_schema": 2, "host": "claude-code", "host_session_id": f"host-{self.sessions}",
                "actor": "Fixture agent", "role": ROLES.get(stage, "implementer"), "model": "fixture-model",
                "started_at": "2026-01-31T09:00:00Z", "ended_at": "2026-01-31T09:30:00Z", "stage": stage}
        if stage == "foundation":
            meta["subject"] = "flow"
        elif stage == "release":
            meta["release"] = {"component": "engine", "version": "v1.0.0"}
        else:
            meta["change_id"] = "CHG-001"
            if stage in COMPONENT_STAGES:
                meta["component"] = "engine"
        meta.update(overrides)
        meta = {k: v for k, v in meta.items() if v is not None}
        meta_file, transcript = self.inputs / f"meta-{self.sessions}.json", self.inputs / f"session-{self.sessions}.jsonl"
        put_json(meta_file, meta)
        transcript.write_bytes(TRANSCRIPT)
        return self.call("evidence", "record", "--kind", "agent-session", "--file", meta_file,
                         "--transcript", transcript)["data"]["evidence"]["id"]

    def set_evidence(self, *stages, value="required"):
        path = self.root / FLOW
        text = path.read_text(encoding="utf-8")
        for stage in stages:
            start = text.index(f"[stages.{stage}]\n")
            end = text.find("\n[", start + 1)
            end = len(text) if end < 0 else end
            block = re.sub(r'session_evidence = "\w+"\n', "", text[start:end])
            block = block.replace(f"[stages.{stage}]\n", f'[stages.{stage}]\nsession_evidence = "{value}"\n', 1)
            text = text[:start] + block + text[end:]
        path.write_text(text, encoding="utf-8")

    def agree_flow(self, *extra, expect=0, issue=None):
        return self.call("foundation", "agree", "--ref", "flow", "--actor", "Fixture owner", "--reason", "Adjusted the flow",
                         *criteria(self.root, "foundation"), *extra, expect=expect, issue=issue)

    def require(self, *stages):
        """Require sessions on `stages` and agree the edited flow (before any run pins its bytes)."""
        self.set_evidence(*stages)
        self.agree_flow()

    def run_verify(self, *extra, component="engine", expect=None):
        # With review enabled a fresh run reports REVIEW_REQUIRED (exit 1) until it is reviewed.
        expect = (1 if self.review else 0) if expect is None else expect
        return self.call("run", "verify", "CHG-001", "--component", component, "--base", self.base, *PRODUCER,
                         *extra, expect=expect)["data"]["run"]

    def report(self, run, *, kind="manual", **changes):
        value = {"model_schema": 2, "kind": kind, "change_id": "CHG-001", "component": run["component"],
                 "run_id": run["id"], "candidate_digest": run["candidate"]["inputs_digest"],
                 "actor": "Synthetic observer", "context": "Observation fixture", "outcome": "pass",
                 "acceptance_ids": ["AC-001"], "checks": ["Observed test"], "limitations": [], "findings": []}
        value.update(changes)
        path = self.inputs / f"report-{len(list(self.inputs.glob('report-*')))}.json"
        put_json(path, value)
        return path

    def second_change(self, change_id="CHG-002", folder=None):
        source = folder or self.workspace / change_id
        record = bundle(source, change_id=change_id, components=("engine",), kind="refactor")
        return source, record


class CitationTest(SessionLinksBase):
    def test_bad_citations_are_rejected_on_decisions_runs_evidence_and_bundles(self):
        implement = self.session("implement")
        define = self.session("define", component=None)
        source, _ = self.second_change()
        self.call("change", "new", "--file", source / "change.json")
        foreign = self.session("define", change_id="CHG-002", component=None)
        run = self.run_verify()
        plain = self.call("evidence", "record", "--file", self.report(run))["data"]["evidence"]["id"]
        bad = {"nonexistent": MISSING, "not a session": plain, "out of scope": foreign}

        for label, value in bad.items():
            with self.subTest(record="decision", case=label):
                issue = self.rejected("change", "start", "CHG-001", "--component", "engine", "--actor", "Fixture",
                                      "--session", value, issue="INVALID_REFERENCE")
                self.assertIn("evidence record --kind agent-session", issue["remediation"])
            with self.subTest(record="run", case=label):
                self.rejected("run", "verify", "CHG-001", "--component", "engine", "--base", self.base, *PRODUCER,
                              "--session", value, issue="INVALID_REFERENCE")
            with self.subTest(record="evidence", case=label):
                self.rejected("evidence", "record", "--file", self.report(run, sessions=[value]), issue="INVALID_REFERENCE")
        self.rejected("change", "start", "CHG-001", "--component", "engine", "--actor", "Fixture", "--session", "EVD-bad",
                      issue="INVALID_INPUT")

        # Bundles: sealing and importing a proposal both check its cited sessions.
        for label, value in bad.items():
            with self.subTest(record="bundle", case=label):
                folder = self.workspace / f"bundle-{label.replace(' ', '-')}"
                _, record = self.second_change("CHG-003", folder)
                record["semantic"]["sessions"] = [value]
                record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
                put_json(folder / "change.json", record)
                self.rejected("change", "seal", folder, issue="INVALID_REFERENCE")
                self.rejected("change", "new", "--file", folder / "change.json", issue="INVALID_REFERENCE")
        folder = self.workspace / "bundle-empty"
        _, record = self.second_change("CHG-003", folder)
        record["semantic"]["sessions"] = []
        record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
        put_json(folder / "change.json", record)
        self.rejected("change", "new", "--file", folder / "change.json", issue="INVALID_INPUT")
        self.call("change", "seal", folder)
        self.assertNotIn("sessions", json.loads((folder / "change.json").read_text())["semantic"])

        # Valid citations are stored sorted and unique; existing records keep their shape.
        start = self.call("change", "start", "CHG-001", "--component", "engine", "--actor", "Fixture",
                          "--session", implement, "--session", define, "--session", implement)["data"]["receipt"]
        decision = json.loads((self.root / next(p for p in start["writes"] if p.startswith(".roclec/decisions/"))).read_text())
        self.assertEqual(decision["sessions"], sorted([implement, define]))
        cited = self.run_verify("--session", implement)
        self.assertEqual(cited["producer"]["sessions"], [implement])
        report = self.call("evidence", "record", "--file", self.report(cited, sessions=[implement]))["data"]["evidence"]
        self.assertEqual(report["sessions"], [implement])
        empty = self.call("evidence", "record", "--file", self.report(cited, sessions=[]))["data"]["evidence"]
        self.assertNotIn("sessions", empty)
        self.assertNotIn("sessions", run["producer"])
        self.assertEqual(self.check_issues(), [])

    def test_inspect_change_lists_sessions_per_stage(self):
        foundation = self.session("foundation")
        define = self.session("define", component=None)
        engine = self.session("implement")
        viewer = self.session("implement", component="viewer")
        plan = self.session("plan")
        release = self.session("release")
        flow = self.call("inspect", "--change", "CHG-001")["data"]["flow"]
        stages = {row["stage"]: row for row in flow["stages"]}
        self.assertEqual(stages["define"]["change"]["sessions"], [define])
        self.assertEqual(stages["approve"]["change"]["sessions"], [])
        self.assertEqual(stages["implement"]["components"]["engine"]["sessions"], [engine])
        self.assertEqual(stages["implement"]["components"]["viewer"]["sessions"], [viewer])
        # A session without a component applies to every component row of its stage.
        self.assertEqual({c: e["sessions"] for c, e in stages["plan"]["components"].items()},
                         {"engine": [plan], "viewer": [plan]})
        self.assertEqual(stages["foundation"]["components"]["engine"]["sessions"], [foundation])
        self.assertEqual(stages["release"]["components"]["engine"]["sessions"], [release])
        self.assertEqual(stages["release"]["components"]["viewer"]["sessions"], [])
        self.assertEqual(stages["verify"]["components"]["engine"]["sessions"], [])
        self.assertNotIn("session_issues", flow)


class GateTest(SessionLinksBase):
    def test_flow_rejects_required_sessions_on_a_person_stage(self):
        raw = (self.root / FLOW).read_bytes()
        self.set_evidence("approve")
        with self.assertRaises(ModelError) as caught:
            project_flow.parse((self.root / FLOW).read_bytes())
        self.assertEqual(caught.exception.issue["code"], "FLOW_INVALID")
        self.assertIn("optional", caught.exception.issue["remediation"])
        self.call("check", "--change", "CHG-001", "--gate", "approve", expect=2, issue="FLOW_INVALID")
        (self.root / FLOW).write_bytes(raw)
        seeded = project_flow.parse(Path(project_flow.__file__).parent.joinpath("assets/project/flow.toml").read_bytes())
        self.assertEqual({row["name"]: row["session_evidence"] for row in seeded["stages"]},
                         {row["name"]: "optional" if row["name"] == "approve" else "required" for row in seeded["stages"]})

    def test_define_session_gates_approval(self):
        source, record = self.second_change()
        self.call("change", "new", "--file", source / "change.json")
        self.call("check", "--change", "CHG-002", "--gate", "approve")  # Optional: nothing demanded.
        self.set_evidence("define")
        issue = self.rejected("check", "--change", "CHG-002", "--gate", "approve", issue="SESSION_REQUIRED", expect=1)
        self.assertEqual((issue["entity"], issue["expected"]), ("CHG-002", "define"))
        self.assertIn("evidence record --kind agent-session --file <meta.json> --transcript <export>", issue["remediation"])
        approve = ("change", "approve", "CHG-002", "--digest", record["proposal_digest"], "--actor", "Fixture owner",
                   "--reason", "Approved", *criteria(self.root, "approve"))
        self.rejected(*approve, issue="SESSION_REQUIRED", expect=1)
        self.session("define", change_id="CHG-001", component=None)  # Another change's session does not count.
        self.rejected(*approve, issue="SESSION_REQUIRED", expect=1)
        define = self.session("define", change_id="CHG-002", component=None)
        self.call("check", "--change", "CHG-002", "--gate", "approve")
        decision = self.call(*approve, "--session", define)["data"]["decision"]
        self.assertEqual(decision["sessions"], [define])

    def test_implement_session_gates_verify(self):
        self.require("implement")
        run = self.run_verify()  # The implement gate demands design/plan sessions only.
        self.assertEqual(run["status"], "pass")
        gate = ("check", "--change", "CHG-001", "--component", "engine", "--gate", "verify")
        issue = self.rejected(*gate, issue="SESSION_REQUIRED", expect=1)
        self.assertEqual((issue["entity"], issue["expected"]), ("CHG-001/engine", "implement"))
        self.assertIn('"optional"', issue["remediation"])
        self.session("implement", component="viewer")
        self.rejected(*gate, issue="SESSION_REQUIRED", expect=1)
        self.session("implement")
        self.call(*gate)

    def test_plan_session_gates_implement_and_counts_without_component(self):
        self.require("plan")
        gate = ("check", "--change", "CHG-001", "--component", "engine", "--gate", "implement")
        self.rejected(*gate, issue="SESSION_REQUIRED", expect=1)
        self.rejected("run", "verify", "CHG-001", "--component", "engine", "--base", self.base, *PRODUCER,
                      issue="SESSION_REQUIRED", expect=1)
        self.session("plan")
        self.call(*gate)

    def test_verify_session_gates_integration_and_integrate_session_gates_release(self):
        self.require("verify", "integrate")
        run = self.run_verify()
        commit(self.root)
        gate = ("check", "--change", "CHG-001", "--component", "engine", "--gate", "integrate")
        self.assertEqual(self.rejected(*gate, issue="SESSION_REQUIRED", expect=1)["expected"], "verify")
        plan = self.workspace / "integration-plan.json"
        self.call("integrate", "prepare", "CHG-001", "--component", "engine", "--run", run["id"], "--out", plan,
                  expect=1, issue="SESSION_REQUIRED")
        self.assertFalse(plan.exists())
        self.session("verify")
        commit(self.root)
        self.call(*gate)
        self.call("integrate", "prepare", "CHG-001", "--component", "engine", "--run", run["id"], "--out", plan)
        self.call("operation", "apply", plan)
        commit(self.root)
        release = ("check", "--gate", "release", "--component", "engine", "--release", "v1.0.0")
        issue = self.rejected(*release, issue="SESSION_REQUIRED", expect=1)
        self.assertEqual((issue["entity"], issue["expected"]), ("CHG-001/engine", "integrate"))
        self.session("integrate")
        self.call("run", "verify", "--release", "v1.0.0", "--component", "engine", "--base", self.base,
                  "--role", "coordinator", "--context", "Synthetic release session")
        commit(self.root)
        self.call(*release)

    def test_release_session_is_matched_to_its_release(self):
        # `release record` demands this through Kernel.require_session (its remote publication is out of scope here).
        self.set_evidence("release")
        release = {"component": "engine", "version": "v1.0.0"}
        def demand():
            parsed = project_flow.parse((self.root / FLOW).read_bytes())
            return Kernel(load_profile(self.root)).require_session("release", parsed, release=release)
        with self.assertRaises(ModelError) as caught:
            demand()
        self.assertEqual((caught.exception.issue["entity"], caught.exception.issue["expected"]), ("engine/v1.0.0", "release"))
        self.session("release", release={"component": "viewer", "version": "v1.0.0"})
        self.assertRaises(ModelError, demand)
        session = self.session("release")
        self.assertEqual(demand(), [session])

    def test_first_bundle_cites_the_define_session_that_preceded_its_import(self):
        define = self.session("define", change_id="CHG-002", component=None)  # CHG-002 is not imported yet.
        folder = self.workspace / "first-bundle"
        _, record = self.second_change("CHG-002", folder)
        record["semantic"]["sessions"] = [define]
        record["proposal_digest"] = digest({k: record[k] for k in ("id", "kind", "semantic")})
        put_json(folder / "change.json", record)
        self.call("change", "seal", folder)
        self.call("change", "new", "--file", folder / "change.json")
        self.assertEqual(json.loads((folder / "change.json").read_text())["semantic"]["sessions"], [define])
        # Before its change exists, a define session cannot name a component it could not validate.
        early = self.inputs / "early-define.json"
        put_json(early, {**json.loads((self.inputs / "meta-1.json").read_text()), "change_id": "CHG-008", "component": "engine"})
        self.rejected("evidence", "record", "--kind", "agent-session", "--file", early,
                      "--transcript", self.inputs / "session-1.jsonl", issue="INVALID_INPUT")
        # Only a define session may name a change that is not imported yet.
        meta = self.inputs / "early-implement.json"
        put_json(meta, {"model_schema": 2, "host": "claude-code", "host_session_id": "early", "actor": "Fixture agent",
                        "role": "implementer", "model": "fixture-model", "started_at": "2026-01-31T09:00:00Z",
                        "ended_at": "2026-01-31T09:30:00Z", "stage": "implement", "change_id": "CHG-009",
                        "component": "engine"})
        self.rejected("evidence", "record", "--kind", "agent-session", "--file", meta, "--transcript",
                      self.inputs / "session-1.jsonl", issue="INVALID_REFERENCE")

    def test_implement_rechecks_define_and_foundation_sessions_under_the_agreed_flow(self):
        # define: required by the agreed flow, skipped at approval through an unagreed edit, caught at implement.
        self.require("define")
        source, record = self.second_change()
        self.call("change", "new", "--file", source / "change.json")
        agreed = (self.root / FLOW).read_bytes()
        self.set_evidence("define", value="optional")
        self.call("change", "approve", "CHG-002", "--digest", record["proposal_digest"], "--actor", "Fixture owner",
                  "--reason", "Approved", *criteria(self.root, "approve"))
        (self.root / FLOW).write_bytes(agreed)
        gate = ("check", "--change", "CHG-002", "--component", "engine", "--gate", "implement")
        issue = self.call(*gate, expect=1, issue="SESSION_REQUIRED")["issues"][0]
        self.assertEqual((issue["entity"], issue["expected"]), ("CHG-002/engine", "define"))
        # foundation: references agreed before the demand still need their sessions at implement.
        self.set_evidence("foundation")
        self.agree_flow("--session", self.session("foundation"))
        self.session("define", component=None)
        gate = ("check", "--change", "CHG-001", "--component", "engine", "--gate", "implement")
        missing = []
        for _ in range(10):
            result = invoke(["--project", str(self.root), "--json", *gate])
            issues = json.loads(result.stdout)["issues"]
            if result.returncode == 0:
                break
            self.assertEqual((result.returncode, issues[0]["code"], issues[0]["expected"]), (1, "SESSION_REQUIRED", "foundation"))
            missing.append(issues[0]["entity"])
            self.session("foundation", subject=issues[0]["entity"])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(missing)
        self.assertNotIn("flow", missing)  # The flow's own agreement already cited its session.

    def test_foundation_session_gates_agreement(self):
        self.set_evidence("foundation")
        issue = self.agree_flow(expect=1, issue="SESSION_REQUIRED")["issues"][0]
        self.assertEqual((issue["entity"], issue["expected"]), ("flow", "foundation"))
        self.session("foundation", subject="architecture")  # Another subject does not count.
        self.agree_flow(expect=1, issue="SESSION_REQUIRED")
        session = self.session("foundation")
        decision = self.agree_flow("--session", session)["data"]["decision"]
        self.assertEqual(decision["sessions"], [session])
        self.call("foundation", "agree", "--ref", "architecture", "--actor", "Fixture owner", "--reason", "Agreed",
                  *criteria(self.root, "foundation"), "--session", session, expect=2, issue="INVALID_REFERENCE")


class ReviewTest(SessionLinksBase):
    review = {"enabled": True}

    def review_file(self, run, context, **changes):
        policy = self.call("inspect", "--change", "CHG-001")["data"]["review_policy"]
        return self.report(run, kind="independent-review", actor="Fixture reviewer", role="reviewer", context=context,
                           policy_id=policy["id"], outcome="ready", **changes)

    def test_review_context_cites_an_independent_reviewer_session(self):
        self.require("review")
        producer = self.session("implement", host_session_id="shared-host")
        run = self.run_verify("--session", producer)
        issue = self.rejected("evidence", "record", "--file", self.review_file(run, "Synthetic reviewer session"),
                              issue="SESSION_REQUIRED")
        self.assertIn("evidence record --kind agent-session", issue["remediation"])
        wrong_role = self.session("review", role="implementer")
        self.rejected("evidence", "record", "--file", self.review_file(run, wrong_role), issue="INVALID_REFERENCE")
        other_component = self.session("review", component="viewer")
        self.rejected("evidence", "record", "--file", self.review_file(run, other_component), issue="INVALID_REFERENCE")
        self.rejected("evidence", "record", "--file", self.review_file(run, producer), issue="INVALID_REFERENCE")
        same_host = self.session("review", host_session_id="shared-host")
        self.rejected("evidence", "record", "--file", self.review_file(run, same_host), issue="SELF_REVIEW_DECLARED", expect=1)
        reviewer = self.session("review", host_session_id="reviewer-host")
        report = self.call("evidence", "record", "--file", self.review_file(run, reviewer))["data"]["evidence"]
        self.assertEqual(report["context"], reviewer)
        self.call("check", "--change", "CHG-001", "--component", "engine", "--gate", "verify")

    def test_optional_review_keeps_free_text_but_resolves_session_ids(self):
        run = self.run_verify()
        self.rejected("evidence", "record", "--file", self.review_file(run, MISSING), issue="INVALID_REFERENCE")
        self.call("evidence", "record", "--file", self.review_file(run, "Synthetic reviewer session"))
        self.call("check", "--change", "CHG-001", "--component", "engine", "--gate", "verify")

    def test_review_session_gates_integration(self):
        self.set_evidence("review")
        kernel = Kernel(load_profile(self.root))
        with self.assertRaises(ModelError) as caught:
            kernel.require_gate_sessions("CHG-001", "engine", "integrate")
        self.assertEqual((caught.exception.issue["code"], caught.exception.issue["expected"]), ("SESSION_REQUIRED", "review"))
        self.session("review")
        Kernel(load_profile(self.root)).require_gate_sessions("CHG-001", "engine", "integrate")
        with self.assertRaises(ModelError):
            Kernel(load_profile(self.root)).require_gate_sessions("CHG-001", "viewer", "integrate")
        # With review disabled for the change, no review session is demanded.
        self.call("review", "policy", "--change", "CHG-001", "--enabled", "false", "--actor", "Fixture owner",
                  "--reason", "No review for this change")
        Kernel(load_profile(self.root)).require_gate_sessions("CHG-001", "viewer", "integrate")


class ProcessFutTest(SessionLinksBase):
    def fut(self, fut_id, scope=None, expect=0, issue=None):
        value = {"model_schema": 2, "id": fut_id, "source": {"location": "retro", "locator": "fixture"},
                 "finding": "The gate blocks too early", "impact": "Rework", "questions": []}
        if scope is not None:
            value["scope"] = scope
        path = self.inputs / f"{fut_id}.json"
        put_json(path, value)
        return self.call("fut", "capture", "--file", path, expect=expect, issue=issue)

    def test_process_friction_links_to_the_flow_agreement_that_addresses_it(self):
        self.fut("FUT-001", "process")
        self.fut("FUT-002")  # No scope: product.
        self.fut("FUT-003", "process")
        self.fut("FUT-004", "elsewhere", expect=2, issue="INVALID_INPUT")
        self.call("fut", "decide", "FUT-003", "--outcome", "discarded", "--actor", "Fixture owner", "--reason", "Not needed")
        self.assertEqual({row["id"]: row["scope"] for row in self.call("list", "futs")["data"]["futs"]},
                         {"FUT-001": "process", "FUT-002": "product", "FUT-003": "process"})
        before_flow = json.loads((self.root / ".roclec/references.json").read_text())
        old_agreement = next(r["decision_id"] for r in before_flow["references"] if r["id"] == "flow")

        for value, code in (("FUT-002", "INVALID_REFERENCE"), ("FUT-404", "INVALID_REFERENCE"),
                            ("FUT-003", "INVALID_REFERENCE")):
            with self.subTest(fut=value):
                before = files(self.root)
                self.agree_flow("--fut", value, expect=2, issue=code)
                self.assertEqual(files(self.root), before)
        self.call("foundation", "agree", "--ref", "architecture", "--actor", "Fixture owner", "--reason", "Agreed",
                  *criteria(self.root, "foundation"), "--fut", "FUT-001", expect=2, issue="INVALID_INPUT")

        (self.root / FLOW).write_text((self.root / FLOW).read_text() + "\n# Adjusted after FUT-001.\n")
        agreement = self.agree_flow("--fut", "FUT-001")["data"]["decision"]
        self.assertEqual(agreement["futs"], ["FUT-001"])
        decide = ("fut", "decide", "--outcome", "promoted", "--actor", "Fixture owner", "--reason", "Flow adjusted")
        self.call(decide[0], decide[1], "FUT-001", *decide[2:], "--target", old_agreement, expect=2, issue="INVALID_REFERENCE")
        self.call(decide[0], decide[1], "FUT-002", *decide[2:], "--target", agreement["id"], expect=2, issue="INVALID_REFERENCE")
        self.call(decide[0], decide[1], "FUT-001", *decide[2:], "--target", agreement["id"])

        view = self.call("inspect", "--fut", "FUT-001")["data"]
        self.assertEqual((view["scope"], view["status"]), ("process", "promoted"))
        self.assertEqual(view["addressed_by"], [{"decision": agreement["id"], "flow": agreement["sources"]["flow"],
                                                 "reason": "Adjusted the flow", "actor": "Fixture owner"}])
        self.assertEqual(view["decisions"][-1]["target"], agreement["id"])
        product = self.call("inspect", "--fut", "FUT-002")["data"]
        self.assertEqual((product["scope"], product["addressed_by"]), ("product", []))
        self.assertEqual(self.check_issues(), [])


if __name__ == "__main__":
    unittest.main()
