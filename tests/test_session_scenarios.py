"""TL.8 (M-34): the shared FL consumer scenarios (agent sessions, gates, storage, flow learning) under unittest.

The same functions run against the installed wheel in `scripts/harness.py`.
"""
from pathlib import Path
import tempfile
import unittest

from scripts.c2_scenarios import (flow_learning_scenarios, session_citation_scenarios, session_lifecycle,
                                  session_review_scenarios, session_storage_scenarios)
from scripts.c3_scenarios import session_release_scenarios
from test_kernel import invoke


class SessionScenariosTest(unittest.TestCase):
    def run_scenario(self, scenario):
        def check(name, condition, detail=""):
            self.assertTrue(condition, f"{name}: {detail}")
        with tempfile.TemporaryDirectory() as directory:
            return scenario(Path(directory), invoke, check)

    def test_seeded_required_flow_demands_each_gate_session(self):
        self.run_scenario(session_lifecycle)

    def test_release_record_demands_a_release_session(self):
        self.run_scenario(session_release_scenarios)

    def test_decisions_store_their_cited_sessions(self):
        self.run_scenario(session_citation_scenarios)

    def test_required_review_binds_the_reviewer_session_and_rejects_self_review(self):
        self.run_scenario(session_review_scenarios)

    def test_storage_policies_redact_keep_local_and_enforce_the_quota(self):
        self.run_scenario(session_storage_scenarios)

    def test_flow_learning_view_and_retrospective(self):
        self.run_scenario(flow_learning_scenarios)


if __name__ == "__main__":
    unittest.main()
