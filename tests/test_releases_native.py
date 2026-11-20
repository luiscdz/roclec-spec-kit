from pathlib import Path
import tempfile
import unittest
import os
import subprocess
import sys

from scripts.c3_scenarios import scenarios, combined_and_fix_scenarios, review_scenarios
from scripts.c3_installation import scenarios as installation_scenarios
from scripts.c3_faults import scenarios as fault_scenarios
from test_kernel import invoke


class NativeReleaseTest(unittest.TestCase):
    def test_public_c3_publication_scenarios(self):
        with tempfile.TemporaryDirectory() as directory:
            scenarios(Path(directory), invoke, lambda name, condition, detail="": self.assertTrue(condition, f"{name}: {detail}"))

    def test_combined_release_and_real_fix_inclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            combined_and_fix_scenarios(Path(directory), invoke, lambda name, condition, detail="": self.assertTrue(condition, f"{name}: {detail}"))

    def test_native_installation_and_consumer_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            installation_scenarios(Path(directory), invoke, lambda name, condition, detail="": self.assertTrue(condition, f"{name}: {detail}"))

    def test_release_and_instruction_recovery(self):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        def inject(code, argv):
            return subprocess.run([sys.executable, "-c", code, *argv], env=env, capture_output=True, text=True, timeout=30)
        with tempfile.TemporaryDirectory() as directory:
            fault_scenarios(Path(directory), invoke, inject, lambda name, condition, detail="": self.assertTrue(condition, f"{name}: {detail}"))

    def test_final_release_review_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            review_scenarios(Path(directory), invoke, lambda name, condition, detail="": self.assertTrue(condition, f"{name}: {detail}"))
