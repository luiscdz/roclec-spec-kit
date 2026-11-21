from pathlib import Path
import os
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts.c2_scenarios import PRODUCER, scenarios, execution_scenarios, conflict_scenarios, edge_scenarios, setup, commit, branch_scenarios
from test_kernel import invoke
from scripts.c2_faults import capture_scenarios, scenarios as fault_scenarios
from scripts.c1_scenarios import bundle, digest, put_json, snapshot, tree
from roclec_spec_kit.agents import contracts
from roclec_spec_kit.verification import REVIEW_ROLES, RUN_ROLES


class VerificationTest(unittest.TestCase):
    def test_branch_history_and_causal_supersession(self):
        with tempfile.TemporaryDirectory() as directory:
            branch_scenarios(Path(directory), invoke,
                             lambda name, condition, detail="": self.assertTrue(condition, f"{name}: {detail}"))

    def test_public_c2_scenarios(self):
        with tempfile.TemporaryDirectory() as directory:
            scenarios(Path(directory), invoke, lambda name, condition, evidence="": self.assertTrue(condition, f"{name}: {evidence}"))

    def test_execution_failure_and_coverage_scenarios(self):
        with tempfile.TemporaryDirectory() as directory:
            execution_scenarios(Path(directory), invoke, lambda name, condition, evidence="": self.assertTrue(condition, f"{name}: {evidence}"))

    def test_interruption_and_recovery_boundaries(self):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        def inject(code, argv):
            return subprocess.run([sys.executable, "-c", code, *argv], env=env, capture_output=True, text=True, timeout=30)
        with tempfile.TemporaryDirectory() as directory:
            check = lambda name, condition, evidence="": self.assertTrue(condition, f"{name}: {evidence}")
            fault_scenarios(Path(directory), invoke, inject, check)
            capture_scenarios(Path(directory), invoke, inject, check)

    def test_competing_plans_do_not_overwrite_a_moved_base(self):
        with tempfile.TemporaryDirectory() as directory:
            conflict_scenarios(Path(directory), invoke, lambda name, condition, evidence="": self.assertTrue(condition, f"{name}: {evidence}"))

    def test_deletions_dirty_candidates_and_separate_code_repos(self):
        with tempfile.TemporaryDirectory() as directory:
            edge_scenarios(Path(directory), invoke, lambda name, condition, evidence="": self.assertTrue(condition, f"{name}: {evidence}"))

    def test_partial_cancellation_preserves_integrated_release_membership(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = setup(Path(directory), invoke)
            def call(*args, expect=0):
                result = invoke(["--project", str(root), "--json", *map(str, args)])
                self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
                return json.loads(result.stdout)["data"]
            run = call("run", "verify", "CHG-001", "--component", "engine", "--base", base, *PRODUCER)["run"]
            commit(root)
            plan = Path(directory) / "plan.json"
            call("integrate", "prepare", "CHG-001", "--component", "engine", "--run", run["id"], "--out", plan)
            call("operation", "apply", plan)
            working = root / ".roclec/changes/CHG-001"
            saved = Path(directory) / "saved-change"
            shutil.copytree(working, saved)
            altered = Path(directory) / "altered-change"
            record = bundle(altered, target=snapshot(ac="AC-003", behavior="different integrated behavior"))
            shutil.copytree(altered, working, dirs_exist_ok=True)
            before = tree(root)
            rejected = invoke(["--project", str(root), "--json", "change", "approve", "CHG-001", "--digest", record["proposal_digest"],
                               "--actor", "fixture user", "--reason", "Attempt to redefine completed scope"])
            self.assertEqual(rejected.returncode, 1, rejected.stdout)
            self.assertEqual(tree(root), before)
            shutil.rmtree(working)
            shutil.copytree(saved, working)
            canceled = call("change", "cancel", "CHG-001", "--actor", "fixture user", "--reason", "Cancel pending scope")
            self.assertEqual(canceled["decision"]["components"], ["viewer"])
            state = call("inspect", "--change", "CHG-001")
            self.assertEqual(state["components"], {"engine": "integrated", "viewer": "canceled"})
            self.assertEqual(state["status"], "partially-integrated")
            call("release", "plan", "engine", "v1.0.0", "--clear", expect=1)
            call("release", "plan", "viewer", "v1.0.0", "--clear")


class DeclaredReviewContextTest(unittest.TestCase):
    """M-28: runs and reviews declare role/context; a declared self-review never satisfies policy."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)
        self.root, self.base = setup(self.workspace, invoke, names=("engine",))
        self.policy = self.call("review", "policy", "--change", "CHG-001", "--enabled", "true", "--actor", "fixture user",
                                "--reason", "Exercise declared review contexts")["data"]["policy"]

    def call(self, *args, expect=0, issue=None):
        result = invoke(["--project", str(self.root), "--json", *map(str, args)])
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        if issue:
            self.assertIn(issue, [i["code"] for i in payload["issues"]], result.stdout)
        return payload

    def run_verify(self, role, context, *, expect=1, issue="REVIEW_REQUIRED"):
        return self.call("run", "verify", "CHG-001", "--component", "engine", "--base", self.base,
                         "--role", role, "--context", context, expect=expect, issue=issue)["data"]["run"]

    def review(self, run, context, *, role="reviewer", actor="R1", expect=0, issue=None):
        record = {"model_schema": 2, "kind": "independent-review", "change_id": "CHG-001", "component": "engine",
                  "run_id": run["id"], "candidate_digest": run["candidate"]["inputs_digest"], "policy_id": self.policy["id"],
                  "actor": actor, "role": role, "context": context, "outcome": "ready", "acceptance_ids": ["AC-001"],
                  "checks": ["Synthetic observation"], "limitations": ["Fixture only"], "findings": []}
        file = self.workspace / "review.json"
        put_json(file, {k: v for k, v in record.items() if v is not None})
        before = tree(self.root)
        payload = self.call("evidence", "record", "--file", file, expect=expect, issue=issue)
        if expect:
            self.assertEqual(tree(self.root), before)
        return payload

    def gate(self, expect=0, issue=None):
        return self.call("check", "--change", "CHG-001", "--component", "engine", "--gate", "verify", expect=expect, issue=issue)

    def strip(self, relative, key):
        path = self.root / relative
        record = json.loads(path.read_text())
        record.pop(key)
        record.pop("digest")
        record["digest"] = digest(record)
        put_json(path, record)

    def test_vocabulary_uses_canonical_roles(self):
        self.assertLessEqual(set(RUN_ROLES) | set(REVIEW_ROLES), set(contracts()) | {"human"})
        self.assertNotIn("reviewer", RUN_ROLES)
        self.assertNotIn("implementer", REVIEW_ROLES)

    def test_invalid_producer_is_rejected_without_writes(self):
        before = tree(self.root)
        rejected = self.call("run", "verify", "CHG-001", "--component", "engine", "--base", self.base,
                             "--role", "reviewer", "--context", "session-a", expect=2, issue="INVALID_INPUT")
        self.assertIn("implementer", rejected["issues"][0]["remediation"])
        for args in (("--context", "session-a"), ("--role", "implementer"), ("--role", "implementer", "--context", " ")):
            self.call("run", "verify", "CHG-001", "--component", "engine", "--base", self.base, *args, expect=2, issue="INVALID_INPUT")
        self.assertEqual(tree(self.root), before)

    def test_self_review_is_whitespace_and_case_insensitive(self):
        run = self.run_verify("coordinator", " Session-A ")
        self.assertEqual(run["producer"], {"role": "coordinator", "context": " Session-A "})
        started = json.loads((self.root / f".roclec/runs/{run['id']}/start.json").read_text())
        self.assertEqual(started["producer"], run["producer"])
        rejected = self.review(run, "session-a", expect=1, issue="SELF_REVIEW_DECLARED")
        self.assertIn("roclec-reviewer", rejected["issues"][0]["remediation"])
        self.review(run, "session-a", role=None, expect=2, issue="INVALID_INPUT")
        self.review(run, "session-b", role="coordinator", expect=2, issue="INVALID_INPUT")
        self.gate(expect=1, issue="REVIEW_REQUIRED")
        accepted = self.review(run, "session-b", role="human")["data"]["evidence"]
        self.assertEqual((accepted["role"], accepted["context"]), ("human", "session-b"))
        self.assertIn(accepted["id"], self.gate()["data"]["evidence"])
        # A later run produced in the reviewer's own declared context makes that review a self-review.
        self.run_verify("implementer", "SESSION-B", issue="SELF_REVIEW_DECLARED")
        self.gate(expect=1, issue="SELF_REVIEW_DECLARED")
        self.run_verify("implementer", "session-c", expect=0, issue=None)
        self.gate()

    def test_unattributed_history_does_not_satisfy_review_policy(self):
        run = self.run_verify("implementer", "session-a")
        review = self.review(run, "session-b")["data"]["evidence"]
        self.gate()
        # Records written before producer attribution: same bytes otherwise, no producer/role.
        for name in ("start.json", "manifest.json"):
            self.strip(f".roclec/runs/{run['id']}/{name}", "producer")
        self.strip(f".roclec/evidence/{review['id']}.json", "role")
        self.call("check")
        blocked = self.gate(expect=1, issue="REVIEW_REQUIRED")
        self.assertIn("--role", blocked["issues"][0]["remediation"])
        self.assertEqual(blocked["issues"][0]["actual"], [review["id"]])
        stale = self.review(run, "session-b", expect=1, issue="EVIDENCE_STALE")
        self.assertIn("--context", stale["issues"][0]["remediation"])
        fresh = self.run_verify("implementer", "session-a")
        self.gate(expect=1, issue="REVIEW_REQUIRED")
        replacement = self.review(fresh, "session-b")["data"]["evidence"]
        self.assertEqual(replacement["supersedes"], [review["id"]])
        self.assertEqual(self.gate()["data"]["evidence"], [replacement["id"]])
