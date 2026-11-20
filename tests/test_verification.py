from pathlib import Path
import os
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts.c2_scenarios import scenarios, execution_scenarios, conflict_scenarios, edge_scenarios, setup, commit
from test_kernel import invoke
from scripts.c2_faults import scenarios as fault_scenarios
from scripts.c1_scenarios import bundle, snapshot, tree


class VerificationTest(unittest.TestCase):
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
            fault_scenarios(Path(directory), invoke, inject, lambda name, condition, evidence="": self.assertTrue(condition, f"{name}: {evidence}"))

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
            run = call("run", "verify", "CHG-001", "--component", "engine", "--base", base)["run"]
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
