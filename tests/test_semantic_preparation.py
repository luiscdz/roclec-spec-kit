from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from scripts.semantic_scenarios import catalog, prepare, product_source, subject_instructions


ORACLE_SHA256 = {
    "SEM-001": "8e15dcf9c4e9b6610117405b0e20f4afa25ea1c1996958ac26189a99ea21cc55",
    "SEM-002": "1d4403559ab64d5664444eaab7cae5f3a1056e1069ed5ae8503abcdb70ff884e",
    "SEM-003": "2cd722bffcf46dc3d89f3ebab9927ef101dbd18d69a954b69513db31fe3ee57e",
    "SEM-004": "844d9d8c06ae68eb4041d3bbd108adba1a21c81ec38b81c0435d2fb3ba5c4063",
    "SEM-005": "0d19214dc81d9882779cf10986c136ab8e00facbb2e880a5a8ad1d98750e4850",
    "SEM-006": "7cb7e0f7b0dcda340bcd3a5df03ee4e5fbb3c6ff17bde125f4c70f497ad828d5",
    "SEM-007": "9001ef65039fa434d9719efecccd267137f2a412db3c534a709e0d57b3bce38e",
    "SEM-008": "29b4d5e7a811f499e33ca2753e4d8d94ccdd3b37fbc1be99837b59d8da558069",
    "SEM-009": "6539f3bbbf3e558ddca9dd117fe535571d93397ab5d8011a30d14151f2186f02",
    "SEM-010": "27a8b8868a91d7851e11a304772d6638784efa1d0e4279e643072ccfcaf7ddfb",
}


class SemanticPreparationTest(unittest.TestCase):
    def test_refuses_to_overwrite_existing_work_before_environment_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "consumer-owned.txt"
            marker.write_bytes(b"preserve existing work\n")
            with self.assertRaisesRegex(ValueError, "overwrite"):
                prepare(root / "missing.whl", root)
            self.assertEqual(marker.read_bytes(), b"preserve existing work\n")
            self.assertEqual(list(root.iterdir()), [marker])

    def test_unknown_case_rejects_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "fixture.whl"
            wheel.write_bytes(b"not used: case validation precedes installation")
            output = Path(directory) / "campaign"
            with self.assertRaisesRegex(ValueError, "existing case IDs"):
                prepare(wheel, output, case_ids=["UNKNOWN"])
            self.assertFalse(output.exists())

    def test_negative_fixture_has_a_real_counterexample_distinct_from_strong_code(self):
        strong, weak = {}, {}
        exec(product_source(), strong)
        exec(product_source(weak=True), weak)
        self.assertEqual(strong["normalize"]("  abC  "), "ABC")
        self.assertEqual(weak["normalize"]("  abC  "), "ABC")
        self.assertEqual(weak["normalize"]("   "), "")
        with self.assertRaises(ValueError):
            strong["normalize"]("   ")
        self.assertEqual(len(strong["normalize"]("x" * 64)), 64)
        with self.assertRaises(ValueError):
            strong["normalize"]("x" * 65)

    def test_catalog_keeps_reserved_cases_distinct_and_execution_pending(self):
        cases = catalog()
        self.assertEqual(len(cases), 10)
        self.assertEqual(sum(c["partition"] == "reserved" for c in cases), 2)
        self.assertEqual(sum(c["partition"] == "main" for c in cases), 8)
        self.assertTrue(all(c["oracle"]["critical"] for c in cases))
        sem_007 = next(c for c in cases if c["id"] == "SEM-007")
        self.assertEqual(sem_007["skills"], ["roclec-coordinator", "roclec-release", "roclec-implement", "roclec-converge"])
        actual = {c["id"]: hashlib.sha256(json.dumps(c["oracle"], ensure_ascii=False, sort_keys=True,
                  separators=(",", ":")).encode()).hexdigest() for c in cases}
        self.assertEqual(actual, ORACLE_SHA256)

    def test_subject_instructions_are_oracle_free_and_classify_failures(self):
        case = next(c for c in catalog() if c["id"] == "SEM-007")
        rendered = subject_instructions(case, Path("/fixture/consumer"), Path("/fixture/result"))
        self.assertIn("RELEASE_UNASSIGNED", rendered)
        self.assertIn("observed domain gate", rendered)
        self.assertIn("technical tool failure", rendered)
        self.assertIn("Never retry the same failed command automatically", rendered)
        self.assertIn("roclec-release", rendered)
        self.assertNotIn("critical", rendered)
        self.assertNotIn(case["oracle"]["next_action"], rendered)
