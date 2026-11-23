"""The scripted knowledge-skill scenarios that scripts/harness.py replays against the installed wheel (TK.8)."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts import c1_scenarios, c2_scenarios
from scripts.c3_installation import skill_installation_scenarios
try:
    from test_kernel import invoke
except ModuleNotFoundError:
    from tests.test_kernel import invoke


class SkillSharedScenariosTest(unittest.TestCase):
    def run_scenario(self, scenario):
        with tempfile.TemporaryDirectory() as directory:
            scenario(Path(directory), invoke, lambda name, condition, detail="": self.assertTrue(condition, f"{name}: {detail}"))

    def test_c1_skill_lifecycle_pin_gate_and_flow(self):
        self.run_scenario(c1_scenarios.skill_scenarios)

    def test_c2_skill_files_are_candidate_inputs_and_copies_operational(self):
        self.run_scenario(c2_scenarios.skill_scenarios)

    def test_c3_skill_copies_divergence_and_authority_map(self):
        self.run_scenario(skill_installation_scenarios)


if __name__ == "__main__":
    unittest.main()
