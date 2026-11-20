import unittest
from unittest.mock import patch

from roclec_spec_kit.causality import record_id, scoped_heads
from roclec_spec_kit.model import identifier


class CausalityTest(unittest.TestCase):
    def test_ulids_remain_monotonic_when_clock_regresses(self):
        with patch("roclec_spec_kit.causality._last_pid", None), patch(
            "roclec_spec_kit.causality.time.time_ns", side_effect=[2_000_000, 1_000_000]
        ):
            first, second = record_id("RUN"), record_id("RUN")
        self.assertEqual(identifier(first, "RUN"), first)
        self.assertEqual(identifier(second, "RUN"), second)
        self.assertLess(first, second)

    def test_partial_observation_and_head_conflicts_ignore_record_order(self):
        base = {"id": "original", "supersedes": [], "scope": ["AC-001", "AC-002"]}
        left = {"id": "branch-A", "supersedes": ["original"], "scope": ["AC-001"]}
        right = {"id": "branch-B", "supersedes": ["original"], "scope": ["AC-001"]}
        reconcile = {"id": "reconciliation", "supersedes": ["branch-A", "branch-B"], "scope": ["AC-001"]}
        for records in ([base, left, right], [right, base, left]):
            self.assertEqual(scoped_heads(records, lambda item: item["scope"]),
                             {"AC-001": [left, right], "AC-002": [base]})
            self.assertEqual(scoped_heads([reconcile, *records], lambda item: item["scope"]),
                             {"AC-001": [reconcile], "AC-002": [base]})
