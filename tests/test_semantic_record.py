import hashlib
import json
import unittest

from scripts.semantic_record import classify


class SemanticRecordTest(unittest.TestCase):
    @staticmethod
    def envelope(ok, issues=(), next_action=None):
        return json.dumps({"model_schema": 1, "ok": ok, "command": "check", "data": None,
                           "issues": list(issues), "next_action": next_action}).encode()

    def test_classifies_success_and_domain_gate(self):
        self.assertEqual(classify(0, self.envelope(True))["exit_class"], "success")
        result = classify(1, self.envelope(False, [{"code": "RELEASE_UNASSIGNED"}]))
        self.assertEqual(result["exit_class"], "domain-gate")
        self.assertEqual(result["issue_codes"], ["RELEASE_UNASSIGNED"])

    def test_classifies_invalid_environment_and_unreadable_output(self):
        invalid = classify(2, self.envelope(False, [{"code": "INVALID_INPUT"}]))
        self.assertEqual(invalid["exit_class"], "invalid-invocation")
        io_error = classify(4, self.envelope(False, [{"code": "IO_ERROR"}]))
        self.assertEqual(io_error["exit_class"], "io-or-environment")
        unknown = classify(1, b"not json")
        self.assertEqual(unknown["exit_class"], "unclassified")
        self.assertIsNone(unknown["envelope_ok"])

    def test_hashes_are_stable_for_raw_evidence(self):
        stdout, stderr = b'{"ok":true}\n', b"warning\n"
        self.assertEqual(hashlib.sha256(stdout).hexdigest(), "e5f1eb4d806641698a35efe20e098efd20d7d57a9b90ee69079d5bb650920726")
        self.assertEqual(hashlib.sha256(stderr).hexdigest(), "86a10149acbe95519ea3283d26d57491ede09bd3010cdb756358f66352236b79")
